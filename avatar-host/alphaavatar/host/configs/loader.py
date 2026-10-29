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
from dataclasses import replace
from enum import Enum
from pathlib import Path, PurePath
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from alphaavatar.core.workspace import ApplicationPaths, WorkspacePaths
from alphaavatar.host.application.config import HostConfig
from alphaavatar.host.sessions.factory import validate_session_config

from .application import ApplicationConfig
from .paths import platform_application_root, resolve_application_paths


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


def _validate(value: Any, *, paths: ApplicationPaths | None = None) -> ApplicationConfig:
    from alphaavatar.agents.configs import AvatarConfig

    data = _mapping(value)
    avatar_data = dict(data)
    application = _mapping(avatar_data.pop("application", {}))
    unknown = set(application) - {"home", "cache_root"}
    if unknown:
        raise ValueError("Unknown application path configuration")

    # ApplicationPaths
    if "home" in application:
        paths = ApplicationPaths.from_root(
            application["home"], cache_root=application.get("cache_root")
        )
    elif paths is None:
        raise ValueError("An explicit application home or ApplicationPaths is required")
    elif "cache_root" in application:
        paths = ApplicationPaths.from_root(paths.root, cache_root=application["cache_root"])

    # HostConfig
    host = HostConfig.model_validate(avatar_data.pop("host", {}))
    validate_session_config(host.rtc)

    # AvatarConfig
    avatar = AvatarConfig.model_validate(avatar_data)

    # WorkspacePaths
    workspace = (
        WorkspacePaths.from_root(avatar.avatar.workspace_root)
        if avatar.avatar.workspace_root is not None
        else paths.workspace(avatar.avatar.id)
    )
    avatar.avatar.workspace_root = str(workspace.root)
    resolved = {
        "application": {"home": str(paths.root), "cache_root": str(paths.cache.root)},
        "host": host.model_dump(mode="python"),
        **avatar.model_dump(mode="python"),
    }

    # payload
    payload = json.dumps(
        resolved,
        default=_snapshot_scalar,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return ApplicationConfig(
        host=host, avatar=avatar, paths=paths, workspace=workspace, payload=payload
    )


def validate_application(value: Any, *, paths: ApplicationPaths | None = None) -> ApplicationConfig:
    return _validate(value, paths=paths)


def restore_application(payload: str) -> ApplicationConfig:
    """Restore explicit roots without consulting the child process environment."""
    return _validate(json.loads(payload))


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

    paths = resolve_application_paths(
        os.environ, default_root=platform_application_root(os.environ, Path.home())
    )
    config = validate_application(data, paths=paths)
    raw_avatar = _mapping(data.get("avatar", {}))
    if raw_avatar.get("workspace_root") is None:
        identity = config.avatar.avatar.id
        if identity not in {".", ".."} and not any(c in identity for c in "/\\\x00"):
            home = Path.home()
            previous = [home / ".local" / "share" / identity]
            if os.name == "posix":
                previous.append(Path("/var/lib") / identity)
            if os.environ.get("XDG_DATA_HOME"):
                previous.append(Path(os.environ["XDG_DATA_HOME"]) / identity)
            config = replace(config, previous_workspace_roots=tuple(previous))

    return config
