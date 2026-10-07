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

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from livekit.agents import Agent, llm

from alphaavatar.agents.avatar.context.internal_tools import get_runtime_context_tool
from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.entrypoints.livekit import LiveKitTurnResponseSink
from alphaavatar.agents.log import logger
from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.persona import PersonaBase
from alphaavatar.agents.router import InteractionRouterBase
from alphaavatar.agents.runtime import AvatarRuntime, SessionRuntime
from alphaavatar.agents.runtime.lifecycle import LifecyclePhase, RuntimePluginLifecycle
from alphaavatar.agents.runtime.plugin import AvatarModule
from alphaavatar.agents.status import StatusEmitter, StatusEvent, StatusType

from .patches import init_avatar_patches
from .turn_controller import AvatarTurnController
from .voice import LiveKitTTSAdapter


class AvatarEngine(Agent):
    def __init__(
        self,
        *,
        avatar_config: AvatarConfig,
        runtime: AvatarRuntime,
    ) -> None:
        self._avatar_config = avatar_config
        self._runtime = runtime

        foundation = runtime.foundation
        if foundation is None or not foundation.loop.ready:
            raise RuntimeError("AvatarEngine requires an initialized Foundation Loop")

        self._loop = foundation.loop
        voice_tts = foundation.voice.tts
        if voice_tts is not None and not isinstance(voice_tts, LiveKitTTSAdapter):
            raise TypeError("The current LiveKit response path requires LiveKitTTSAdapter")

        # Step 1: initialize perception plugins and tools plugins.
        self._status: StatusEmitter = avatar_config.status.get_plugin(runtime=runtime)
        self._router: InteractionRouterBase = avatar_config.router.get_plugin(runtime=runtime)
        self._memory: MemoryBase = avatar_config.memory.get_plugin(
            runtime=runtime, avatar_id=avatar_config.avatar.id
        )
        self._persona: PersonaBase = avatar_config.persona.get_plugin(runtime)
        self._tools: list[llm.FunctionTool | llm.RawFunctionTool] = avatar_config.tools.get_tools(
            runtime,
            status_emitter=self._status,
        )
        self._tools.append(get_runtime_context_tool())

        # Step 2: initialize runtime capability.
        self._runtime.capability_registry.collect(self._memory, self._persona)

        # Step 3: bind memory and persona to runtime context.
        self._context_manager = foundation.context
        self._context_manager.bind_sources(memory=self._memory, persona=self._persona)
        super().__init__(
            instructions=self._context_manager.initial_instructions,
            llm=avatar_config.llm.get_plugin(),
            turn_detection="manual",
            stt=None,
            vad=None,
            tts=voice_tts.provider if voice_tts is not None else None,
            allow_interruptions=avatar_config.voice.allow_interruptions,
            tools=self._tools,
        )

        # Step4: Avatar Turn Controller init
        self._turn_controller = AvatarTurnController(
            runtime=runtime,
            sink=LiveKitTurnResponseSink(session_provider=lambda: self.session),
        )

        # Step 5: manage Agent-owned consumers before enabling the Router.
        self._plugin_lifecycle = RuntimePluginLifecycle(
            phases=(
                LifecyclePhase.create(
                    "avatar-plugins-perception",
                    (
                        self._persona,
                        self._memory,
                        self._turn_controller,
                    ),
                ),
                LifecyclePhase.create(
                    "avatar-plugins-perception-router",
                    (self._router,),
                ),
            )
        )

    @property
    def session_runtime(self) -> SessionRuntime:
        return self._runtime.session

    @property
    def memory(self) -> MemoryBase:
        return self._memory

    @property
    def persona(self) -> PersonaBase:
        return self._persona

    @staticmethod
    async def _run_shutdown_step(
        label: str, operation: Callable[[], Any], errors: list[Exception]
    ) -> None:
        try:
            result = operation()

            if inspect.isawaitable(result):
                await result

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("AvatarEngine shutdown step failed: %s", label)
            error = RuntimeError(f"AvatarEngine shutdown step failed: {label}")
            error.__cause__ = exc
            errors.append(error)

    def notify_ready(self) -> None:
        self._status.emit_nowait(
            StatusEvent(
                type=StatusType.READY, source=AvatarModule.AVATAR_ENGINE, stage="session_ready"
            )
        )

    async def on_session_start(self) -> None:
        if not self._loop.ready:
            raise RuntimeError("AvatarEngine cannot start with an unready Loop")
        init_avatar_patches(self)
        await self._plugin_lifecycle.start()

    async def on_session_stop(self) -> None:
        errors: list[Exception] = []

        # Loop consumers may still commit records to Memory during their cleanup.
        await self._run_shutdown_step("loop shutdown", self._loop.aclose, errors)
        wait_pending = getattr(getattr(self._chat_ctx, "items", None), "wait_pending", None)

        if callable(wait_pending):
            await self._run_shutdown_step(
                "chat context pending flush",
                wait_pending,
                errors,
            )

        await self._run_shutdown_step(
            "runtime plugin shutdown",
            self._plugin_lifecycle.stop,
            errors,
        )

        await self._run_shutdown_step(
            "session user path migration flush",
            lambda: self._runtime.session.flush_user_path_migrations(remove_old=True),
            errors,
        )

        if errors:
            raise ExceptionGroup("AvatarEngine shutdown completed with errors.", errors)
