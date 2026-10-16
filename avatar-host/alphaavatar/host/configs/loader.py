# Copyright 2026 AlphaAvatar project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path, PurePath
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from alphaavatar.host.application.config import HostConfig
from alphaavatar.host.sessions.factory import validate_session_config

from .application import ApplicationConfig


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError("Application configuration must be a mapping with string keys")
    return dict(value)


def _snapshot_scalar(value: Any) -> Any:
    # This is a private launch payload, not a log/export: masking a SecretStr here would
    # silently replace a configured credential. ApplicationConfig hides payload from repr.
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, PurePath | UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, set | frozenset):
        return sorted(value)
    raise ValueError("Application configuration contains a non-serializable value")


def _validate(value: Any, *, restored: bool) -> ApplicationConfig:
    from alphaavatar.agents.configs import AvatarConfig

    data = _mapping(value)
    avatar_data = dict(data)
    host = HostConfig.model_validate(avatar_data.pop("host", {}))
    validate_session_config(host.rtc)

    context = {"resolved_workspace": True} if restored else None
    avatar = AvatarConfig.model_validate(avatar_data, context=context)

    # Resolve defaults and Avatar identity once. Re-reading raw YAML in a fresh interpreter
    # would create another default identity and append avatar_id to the workspace again.
    resolved = {"host": host.model_dump(mode="python"), **avatar.model_dump(mode="python")}
    payload = json.dumps(
        resolved,
        default=_snapshot_scalar,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return ApplicationConfig(host=host, avatar=avatar, payload=payload)


def validate_application(value: Any) -> ApplicationConfig:
    return _validate(value, restored=False)


def restore_application(payload: str) -> ApplicationConfig:
    """Strictly validate a parent-owned resolved snapshot without repeating workspace resolution."""
    return _validate(json.loads(payload), restored=True)


def load_application(path: str | Path, overrides: Sequence[str] = ()) -> ApplicationConfig:
    import yaml
    from omegaconf import OmegaConf
    from omegaconf.errors import OmegaConfBaseException

    config_path = Path(path).expanduser().resolve(strict=True)
    text = config_path.read_text(encoding="utf-8")
    try:
        if config_path.suffix.lower() in (".yaml", ".yml"):
            data = _mapping(yaml.safe_load(text))
        elif config_path.suffix.lower() == ".json":
            data = _mapping(json.loads(text))
        else:
            raise ValueError("Application configuration must be YAML or JSON")
        merged = OmegaConf.merge(data, OmegaConf.from_dotlist(list(overrides)))
        data = _mapping(OmegaConf.to_container(merged, resolve=True))
    except (yaml.YAMLError, OmegaConfBaseException):
        # These exceptions may render the original line, including an inline credential.
        raise ValueError("Invalid YAML, configuration override, or interpolation") from None

    duration = os.getenv("ALPHAAVATAR_MAX_SESSION_SECONDS")
    if duration is not None:
        host = _mapping(data.get("host", {}))
        execution = _mapping(host.get("execution", {}))
        if "max_session_seconds" not in execution:
            execution["max_session_seconds"] = int(duration)
        host["execution"] = execution
        data["host"] = host

    return validate_application(data)
