# Copyright 2025 AlphaAvatar project
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

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum

from livekit.agents import Plugin

from .log import logger

RunnerBootstrapFn = Callable[[], None]


class AvatarModule(str, Enum):
    # Engine
    AVATAR_ENGINE = "avatar_engine"

    # Voice modules
    VOICE_VAD = "voice_vad"
    VOICE_STT = "voice_stt"
    VOICE_TTS = "voice_tts"

    # Interaction router modules
    INTERACTION_ROUTER = "interaction_router"

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
    PROFILER = "persona_profiler"
    SPEAKER = "persona_speaker"
    FACE = "persona_face"

    # deepresearch
    DEEPRESEARCH = "deepresearch"

    # rag
    RAG = "rag"

    # mcp
    MCP = "mcp"


class AvatarPlugin(Plugin):
    avatar_registered_plugins: dict[AvatarModule, dict[str, Plugin]] = {
        module_name: {} for module_name in AvatarModule
    }

    _runner_bootstraps: dict[str, RunnerBootstrapFn] = {}

    @classmethod
    def register_avatar_plugin(cls, module: AvatarModule, name: str, plugin: Plugin) -> None:
        if threading.current_thread() != threading.main_thread():
            raise RuntimeError("Plugins must be registered on the main thread")

        if name in cls.avatar_registered_plugins[module]:
            raise ValueError(f"AvatarPlugin[{module}] `{name}` already registered.")

        cls.avatar_registered_plugins[module][name] = plugin
        cls.register_plugin(plugin)

    @classmethod
    def get_avatar_plugin(cls, module: AvatarModule, name: str, *args, **kwargs):
        module_plugins = cls.avatar_registered_plugins[module]
        if name not in module_plugins:
            logger.warning(
                f"Plugin {name} is not registered for module {module}. {module} Module only has plugins: {list(module_plugins.keys())}."
            )
            return None

        return module_plugins[name].get_plugin(*args, **kwargs)

    @classmethod
    def register_inference_runner_bootstrap(
        cls,
        name: str,
        fn: Callable[[], None],
        *,
        override: bool = False,
    ) -> None:
        if name in cls._runner_bootstraps and not override:
            logger.warning("Inference runner bootstrap already registered: %s, skipped", name)
            return

        cls._runner_bootstraps[name] = fn

    @classmethod
    def bootstrap_inference_runners(cls) -> None:
        """
        Called once by AlphaAvatar runtime after config parsing and before
        LiveKit AgentServer starts.

        Core does not know plugin-specific runner classes.
        """
        for name, fn in cls._runner_bootstraps.items():
            try:
                logger.info("Bootstrapping inference runners for plugin: %s", name)
                fn()
            except Exception as e:
                raise RuntimeError(
                    f"Failed to bootstrap inference runners for plugin '{name}': {e}"
                ) from e


class AvatarRuntimePlugin(ABC):
    """
    Base lifecycle interface for session-scoped runtime plugins.

    Long-lived dependencies must be injected through the constructor.
    Lifecycle methods only express session start and stop.
    """

    @abstractmethod
    async def on_session_start(self) -> None:
        """Start session-scoped tasks and acquire session resources."""
        raise NotImplementedError

    @abstractmethod
    async def on_session_stop(self) -> None:
        """Stop session-scoped tasks and release session resources."""
        raise NotImplementedError
