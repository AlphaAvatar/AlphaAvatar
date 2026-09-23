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

from abc import ABC, abstractmethod
from enum import Enum
from logging import Logger
from typing import Any, ClassVar


class AvatarModule(str, Enum):
    # Engine
    AVATAR_ENGINE = "avatar_engine"

    # Voice modules
    VOICE_VAD = "voice_vad"
    VOICE_STT = "voice_stt"
    VOICE_TTS = "voice_tts"

    # Interaction router modules
    ROUTER = "router"

    # Status modules
    STATUS = "status"

    # Intention modules
    INTENTION = "intention"

    # Character modules
    CHARACTER = "character"

    # Memory modules
    MEMORY = "memory"

    # Persona modules
    PERSONA = "persona"

    # tools
    DEEPRESEARCH = "deepresearch"
    RAG = "rag"
    MCP = "mcp"


class AvatarModulePlugin(ABC):
    """Process-scoped module factory; created instances own their runtime state."""

    _registry: ClassVar[dict[AvatarModule, dict[str, AvatarModulePlugin]]] = {}

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
    def register(cls, module: AvatarModule, name: str, plugin: AvatarModulePlugin) -> None:
        module = AvatarModule(module)
        if not isinstance(name, str) or not name or name != name.strip():
            raise ValueError("Plugin name cannot be empty or contain surrounding whitespace")
        if not isinstance(plugin, AvatarModulePlugin):
            raise TypeError("Module plugins must inherit AvatarModulePlugin")

        plugins = cls._registry.setdefault(module, {})
        if name in plugins:
            raise ValueError(f"Plugin {module.value}:{name} is already registered")
        plugins[name] = plugin

    @classmethod
    def create(cls, module: AvatarModule, name: str | None, *args: Any, **kwargs: Any) -> Any:
        module = AvatarModule(module)
        if name is None:
            return None

        plugins = cls._registry.get(module, {})
        if name not in plugins:
            available = ", ".join(sorted(plugins)) or "none"
            raise ValueError(f"Unknown plugin {module.value}:{name!r}; available: {available}")
        return plugins[name].get_plugin(*args, **kwargs)

    @classmethod
    def registered_packages(cls) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                plugin.package for plugins in cls._registry.values() for plugin in plugins.values()
            )
        )

    @abstractmethod
    def get_plugin(self, *args: Any, **kwargs: Any) -> Any:
        """Construct a module instance using explicitly supplied dependencies."""
        raise NotImplementedError
