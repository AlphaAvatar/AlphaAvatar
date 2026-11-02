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
"""Safe projections of an accepted configuration for people and tools.

The launch payload keeps real credentials and is never shown. This view keeps typed plugin
selections, runtime parameters and resolved paths; plugin-defined mappings keep only their
structure and non-text values, and every string that may carry a credential is masked.
"""

from __future__ import annotations

import json
import re
import typing
from typing import Any

from pydantic import BaseModel

from alphaavatar.core.log import error_fields, format_error
from alphaavatar.core.log.records import Redactor

from .application import ApplicationConfig

HIDDEN = "[hidden]"
REDACTED = "[redacted]"
_SENSITIVE = re.compile(r"(?i)token|secret|passw|api[_-]?key|auth|credential|cookie|private")
_SCHEME = re.compile(r"(?i)^(?:Bearer|Basic)\s+")


def _opaque(annotation: Any) -> bool:
    # Untyped plugin mappings cannot say which of their values are credentials.
    return annotation is dict or typing.get_origin(annotation) is dict


def _hide(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _hide(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_hide(item) for item in value]
    return HIDDEN if isinstance(value, str) else value


def _typed(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {name: _typed(name, item) for name, item in value.items()}
    if isinstance(value, list):
        return [_typed(key, item) for item in value]
    return REDACTED if isinstance(value, str) and _SENSITIVE.search(key) else value


def _model(model: BaseModel, dumped: dict[str, Any]) -> dict[str, Any]:
    view = {}
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            view[name] = _model(value, dumped[name])
        elif _opaque(field.annotation):
            view[name] = _hide(dumped[name])
        else:
            view[name] = _typed(name, dumped[name])
    return view


def _secrets(value: Any, key: str = "") -> set[str]:
    """Credential values present anywhere in the launch payload, under sensitive keys."""
    if isinstance(value, dict):
        return {secret for name, item in value.items() for secret in _secrets(item, str(name))}
    if isinstance(value, list):
        return {secret for item in value for secret in _secrets(item, key)}
    if isinstance(value, str) and _SENSITIVE.search(key) and len(value) >= 4:
        return {value, _SCHEME.sub("", value)}
    return set()


def describe_application(config: ApplicationConfig) -> dict[str, Any]:
    """The effective configuration with credentials removed; safe for text or JSON output."""
    view = {
        "application": {"home": str(config.paths.root), "cache_root": str(config.paths.cache.root)},
        "host": _model(config.host, config.host.model_dump(mode="json")),
        **_model(config.avatar, config.avatar.model_dump(mode="json")),
    }
    secrets = sorted(_secrets(json.loads(config.payload)), key=len, reverse=True)
    redact = Redactor()  # The same boundary as Host logs: environment secrets and URLs.

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if not isinstance(value, str) or value in (HIDDEN, REDACTED):
            return value
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return redact(value)

    return scrub(view)


def describe_error(error: BaseException) -> dict[str, Any]:
    """Structured failure metadata: type, field locations and the bounded diagnostic only."""
    return {
        "type": type(error).__name__,
        "fields": list(error_fields(error)),
        "diagnostic": format_error(error),
    }
