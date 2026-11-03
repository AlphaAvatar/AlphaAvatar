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
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from alphaavatar.core.log import error_fields
from alphaavatar.core.log.records import Redactor

from .application import ApplicationConfig
from .bundles import ConfigSource, format_failure

HIDDEN = "[hidden]"
REDACTED = "[redacted]"
_SENSITIVE = re.compile(r"(?i)token|secret|passw|api[_-]?key|auth|credential|cookie|private")
_SCHEME = re.compile(r"(?i)^(?:Bearer|Basic)\s+")


def _opaque(annotation: Any) -> bool:
    # Untyped plugin mappings cannot say which of their values are credentials.
    return annotation is dict or typing.get_origin(annotation) is dict


def _hide(value: Any) -> Any:
    if isinstance(value, dict):
        # Plugin-defined keys are data; _DynamicKey marks them for the output boundary.
        return {_DynamicKey(key): _hide(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_hide(item) for item in value]
    return HIDDEN if isinstance(value, str) else value


class _DynamicKey(str):
    """A mapping key taken from configuration data rather than from a model field."""


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
    if isinstance(value, str) and _SENSITIVE.search(key):
        # Short or empty remainders (for example "Bearer ") would rewrite ordinary text.
        return {secret for secret in (value, _SCHEME.sub("", value)) if len(secret.strip()) >= 4}
    return set()


def output_scrubber(config: ApplicationConfig | None = None) -> Callable[[Any], Any]:
    """One output boundary: known credentials, Host log redaction and control characters.

    Without an accepted configuration only the Host log redaction and cleaning apply.
    """
    payload = json.loads(config.payload) if config is not None else {}
    secrets = sorted(_secrets(payload), key=len, reverse=True)
    redact = Redactor()  # The same boundary as Host logs: environment secrets and URLs.

    def text(value: str) -> str:
        if value in (HIDDEN, REDACTED):
            return value
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return redact(value, limit=None)  # Complete values: long paths stay copyable.

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            # Model field names are fixed output structure; only data keys are filtered.
            return {
                text(str(key)) if isinstance(key, _DynamicKey) else key: scrub(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return text(value) if isinstance(value, str) else value

    return scrub


def describe_application(config: ApplicationConfig) -> dict[str, Any]:
    """The effective configuration with credentials removed; safe for text or JSON output."""
    view = {
        "application": {"home": str(config.paths.root), "cache_root": str(config.paths.cache.root)},
        "host": _model(config.host, config.host.model_dump(mode="json")),
        **_model(config.avatar, config.avatar.model_dump(mode="json")),
    }
    return output_scrubber(config)(view)


def describe_summary(
    config: ApplicationConfig, source: ConfigSource | None = None
) -> dict[str, Any]:
    """What check reports, through the same boundary as the full view.

    Only the selected file or bundle, typed selections and facts derived from them: plugin
    names, vector backend kinds, the on/off switches of vision and of the built-in router,
    memory and persona processors, enabled tools, runner workers and the health address,
    never endpoints or other plugin-defined settings.
    """
    from alphaavatar.agents.runtime.inference import plan_inference_runners
    from alphaavatar.agents.utils.vdb.config import vdb_backend

    avatar, host = config.avatar, config.host

    def store(section: BaseModel) -> dict[str, Any]:
        # The same backend choice the inference plan makes when the Host starts.
        backend = vdb_backend(section.vdb_config) if section.plugin == "default" else None
        return {"plugin": section.plugin, "vdb": backend}

    def switches(options: BaseModel, **paths: str) -> dict[str, bool]:
        # Each built-in plugin's own schema, as at start: omitted switches take its defaults.
        values = {}
        for name, path in paths.items():
            section = options
            for part in path.split("."):
                section = getattr(section, part)
            values[name] = section.enabled
        return values

    memory = store(avatar.memory)
    if avatar.memory.plugin == "default":
        from alphaavatar.plugins.memory.config import DefaultMemoryConfig

        options = DefaultMemoryConfig.model_validate(avatar.memory.init_config)
        names = ("retrieval", "conversation", "tool", "environment")
        memory |= switches(options, **{name: name for name in names})
    persona = store(avatar.persona)
    if avatar.persona.plugin == "default":
        from alphaavatar.plugins.persona.config import DefaultPersonaConfig

        options = DefaultPersonaConfig.model_validate(avatar.persona.init_config)
        persona |= switches(options, profiler="profiler", speaker="speaker", face="face")
    router: dict[str, Any] = {"plugin": avatar.router.plugin}
    if avatar.router.plugin == "default":
        from alphaavatar.plugins.router.config import RouterConfig

        options = RouterConfig.model_validate(avatar.router.init_config)
        router |= switches(
            options,
            audio_activity="audio_activity",
            semantic_addressing="addressing.semantic",
            visual_addressing="addressing.visual",
            turn_taking="turn_taking",
            interruption="turn_taking.interruption",
        )
    mcp = avatar.tools.mcp
    inference = avatar.runtime.inference
    runners = plan_inference_runners(avatar)  # The plan the Host will start, checked again.
    selected = (
        {"config": {"bundle": source.bundle, "default": source.default, "file": str(source.path)}}
        if source is not None
        else {}
    )
    return output_scrubber(config)(
        {
            **selected,
            "avatar_id": avatar.avatar.id,
            "home": str(config.paths.root),
            "workspace": str(config.workspace.root),
            "plugins": {
                "rtc": host.rtc.backend,
                "loop": avatar.loop.plugin,
                "context": avatar.context.plugin,
                "voice": {
                    part: getattr(avatar.voice, part).plugin for part in ("vad", "stt", "tts")
                },
                "vision": {
                    "enabled": avatar.vision.enabled,
                    "input": avatar.vision.input_mode.value,
                },
                "router": router,
                "status": {"plugin": avatar.status.plugin, "enabled": avatar.status.enabled},
                "character": avatar.character.plugin,
                "memory": memory,
                "persona": persona,
                "tools": {
                    "deepresearch": avatar.tools.deepresearch.plugin,
                    "rag": avatar.tools.rag.plugin,
                    "mcp": {"plugin": mcp.plugin, "servers": len(mcp.servers)}
                    if mcp.enabled and mcp.plugin is not None
                    else None,
                },
            },
            "inference": {method: inference.workers(method) for method in runners},
            "health": {"bind": host.health.bind, "port": host.health.port},
        }
    )


def describe_error(error: BaseException) -> dict[str, Any]:
    """Structured failure metadata: type, field locations and the bounded diagnostic only."""
    return {
        "type": type(error).__name__,
        "fields": list(error_fields(error)),
        "diagnostic": format_failure(error),
    }
