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

import inspect
from abc import ABC, abstractmethod
from enum import Enum
from logging import Logger
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel

    from alphaavatar.agents.configs.avatar_config import AvatarConfig
    from alphaavatar.agents.runtime.inference import InferenceRunner


class AvatarModule(str, Enum):
    """Capability types, each implemented by name: ``voice.stt`` by ``openai_segment``.

    Installed packages declare implementations as entry points in the group
    ``alphaavatar.<type>``, named as configurations select them.
    """

    LOOP = "loop"
    CONTEXT = "context"

    # Provider
    PROVIDER_LLM = "provider.llm"
    PROVIDER_EMBEDDING = "provider.embedding"

    # Voice modules
    VOICE_VAD = "voice.vad"
    VOICE_STT = "voice.stt"
    VOICE_TTS = "voice.tts"

    # Interaction router modules
    ROUTER = "router"

    # Status modules
    STATUS = "status"

    # Character modules
    CHARACTER = "character"

    # Memory modules
    MEMORY = "memory"

    # Persona modules
    PERSONA = "persona"

    # tools
    DEEPRESEARCH = "tools.deepresearch"
    RAG = "tools.rag"
    MCP = "tools.mcp"

    @property
    def group(self) -> str:
        return f"alphaavatar.{self.value}"


def plugin_requirement(name: str, *extras: str) -> str:
    """The distribution that installs plugin ``alphaavatar.plugins.<name>``, as a requirement."""
    return f"alpha-avatar-plugins-{name}" + (f"[{','.join(extras)}]" if extras else "")


class AvatarModulePlugin(ABC):
    """An implementation's process-scoped factory, the class its entry point names; created
    instances own their runtime state."""

    def __init__(
        self, title: str, version: str, package: str, logger: Logger | None = None
    ) -> None:
        if not package:
            raise ValueError("Plugin package cannot be empty")
        self._title = title
        self._version = version
        self._package = package
        self._logger = logger

    @property
    def title(self) -> str:
        return self._title

    @property
    def version(self) -> str:
        return self._version

    @property
    def package(self) -> str:
        return self._package

    @classmethod
    def create(cls, module: AvatarModule, name: str | None, *args: Any, **kwargs: Any) -> Any:
        from .resolution import resolve_plugin

        if name is None:
            return None

        return resolve_plugin(module, name).factory.get_plugin(*args, **kwargs)

    def settings(self, init_config: dict[str, Any]) -> BaseModel | None:
        """Its init_config validated as ``get_plugin`` reads it, before anything starts; None
        when it takes none or checks its own when created."""
        return None

    def supports(self, option: str) -> bool:
        """Whether its implementation takes ``option``, a setting implementations of one kind
        may or may not have, checked before anything starts: a parameter ``get_plugin`` names.
        Taking any keyword is not supporting each: a factory that passes them on to what it
        creates says for itself which it supports."""
        parameter = inspect.signature(self.get_plugin).parameters.get(option)
        return parameter is not None and parameter.kind in (
            parameter.POSITIONAL_OR_KEYWORD,
            parameter.KEYWORD_ONLY,
        )

    def inference_runners(self, config: AvatarConfig) -> tuple[type[InferenceRunner], ...]:
        """The runners this implementation uses under ``config``, planned before any starts."""
        return ()

    @abstractmethod
    def get_plugin(self, *args: Any, **kwargs: Any) -> Any:
        """Construct a module instance using explicitly supplied dependencies."""
        raise NotImplementedError
