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
"""Avatar Launch Engine"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterable, Callable, Sequence
from typing import Any
from uuid import uuid4

from livekit.agents import Agent, ModelSettings, llm, tts as livekit_tts
from livekit.agents.types import FlushSentinel

from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.entrypoints.livekit import (
    LiveKitModelInput,
    LiveKitTurnInput,
    LiveKitTurnResponseSink,
)
from alphaavatar.agents.entrypoints.schema.room_type import RoomType
from alphaavatar.agents.log import logger
from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.persona import PersonaBase
from alphaavatar.agents.plugin import AvatarModule, AvatarRuntimePlugin
from alphaavatar.agents.router import InteractionRouterBase, InteractionRouterDependencies
from alphaavatar.agents.runtime import (
    AvatarRuntime,
    SessionRuntime,
    TurnInputModality,
    TurnSnapshot,
)
from alphaavatar.agents.status import (
    StatusEmitter,
    StatusEvent,
    StatusType,
)
from alphaavatar.core.output import OutputLane

from .context import (
    AvatarContextManager,
    AvatarContextStatus,
    extract_answer_text,
)
from .context.internal_tools import get_runtime_context_tool
from .lifecycle import LifecyclePhase, RuntimePluginLifecycle
from .patches import init_avatar_patches
from .turn_controller import AvatarTurnController
from .voice import LiveKitTTSAdapter


class AvatarEngine(Agent):
    def __init__(
        self,
        *,
        avatar_config: AvatarConfig,
        runtime: AvatarRuntime,
        rtc_adapters: dict[str, Sequence[AvatarRuntimePlugin]],
    ) -> None:
        self._avatar_config = avatar_config
        self._runtime = runtime
        self._rtc_adapters = rtc_adapters

        # Step 1: initialize temporary LiveKit model/response adapters.
        self._livekit_model_input = LiveKitModelInput(clock=runtime.clock)
        self._livekit_turn_input = LiveKitTurnInput(
            clock=runtime.clock,
            turn_runtime=runtime.turn,
        )

        # Step 2: initialize runtime plugins and tools.
        self._livekit_tts: livekit_tts.TTS | None = avatar_config.voice.get_tts_plugin()
        self._tts = (
            LiveKitTTSAdapter(self._livekit_tts, owns_provider=False)
            if self._livekit_tts is not None
            else None
        )
        self._status: StatusEmitter = avatar_config.status.get_plugin(
            runtime=runtime,
        )
        self._router: InteractionRouterBase = avatar_config.router.get_plugin(
            dependencies=InteractionRouterDependencies(
                runtime=runtime,
                vad=avatar_config.voice.get_vad_plugin(inference_executor=runtime.inference),
                stt=avatar_config.voice.get_stt_plugin(),
                tts=self._tts,
            )
        )
        self._memory: MemoryBase = avatar_config.memory.get_plugin(
            runtime=runtime,
            avatar_id=avatar_config.avatar.id,
        )
        self._persona: PersonaBase = avatar_config.persona.get_plugin(runtime)
        self._tools: list[llm.FunctionTool | llm.RawFunctionTool] = avatar_config.tools.get_tools(
            runtime,
            status_emitter=self._status,
        )
        self._tools.append(get_runtime_context_tool())

        # Step 3: initialize per-call model context preparation.
        self._context_manager = AvatarContextManager(
            avatar_config=self._avatar_config,
            runtime=self._runtime,
            memory=self._memory,
            persona=self._persona,
        )

        # Step 4: initialize the underlying LiveKit Agent.
        super().__init__(
            instructions=self._context_manager.initial_instructions,
            llm=self._avatar_config.llm.get_plugin(),
            turn_detection="manual",
            stt=None,
            vad=None,
            tts=self._livekit_tts,
            allow_interruptions=self._avatar_config.voice.allow_interruptions,
            tools=self._tools,
        )

        # Step5: Avatar Turn Controller init
        self._turn_controller = AvatarTurnController(
            runtime=runtime,
            sink=LiveKitTurnResponseSink(
                session_provider=lambda: self.session,
            ),
        )

        # Step 6: configure staged plugin lifecycle.
        #
        # Consumers start concurrently before any producer is allowed to publish.
        # During shutdown, producers stop concurrently before consumers stop.
        self._plugin_lifecycle = RuntimePluginLifecycle(
            phases=(
                LifecyclePhase.create(
                    "avatar-rtc-output",
                    tuple(self._rtc_adapters.get("outputs", ())),
                ),
                LifecyclePhase.create(
                    "perception_consumers",
                    (
                        self._persona,
                        self._memory,
                        self._turn_controller,
                    ),
                ),
                LifecyclePhase.create(
                    "interaction_router",
                    (self._router,),
                ),
                LifecyclePhase.create(
                    "avatar-rtc-input",
                    tuple(self._rtc_adapters.get("inputs", ())),
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

    """Helper Op"""

    @staticmethod
    async def _run_shutdown_step(
        label: str,
        operation: Callable[[], Any],
        errors: list[Exception],
    ) -> None:
        try:
            result = operation()

            if inspect.isawaitable(result):
                await result

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "AvatarEngine shutdown step failed: %s",
                label,
            )

            error = RuntimeError(f"AvatarEngine shutdown step failed: {label}")
            error.__cause__ = exc
            errors.append(error)

    def _ensure_turn_snapshot(self, chat_ctx: llm.ChatContext) -> TurnSnapshot:
        message = self._livekit_turn_input.latest_user_message(chat_ctx)

        if message is not None:
            snapshot = self._runtime.turn.get(message.id)
            if snapshot is not None:
                return snapshot

        snapshot = self._livekit_turn_input.commit_chat_context(
            chat_ctx,
            source="livekit_llm_node",
        )
        if snapshot is not None:
            return snapshot

        if self._runtime.turn.latest is not None:
            return self._runtime.turn.latest

        return self._runtime.turn.commit_input(
            input_id=f"system:{uuid4().hex}",
            modality=TurnInputModality.SYSTEM,
            metadata={"source": "livekit_llm_node_system_trigger"},
        )

    """Base Op"""

    async def on_enter(self) -> None:
        init_avatar_patches(self)

        await self._plugin_lifecycle.start()

        if self._runtime.context.interaction_method.room_type == RoomType.WEB_APP.value:
            self._status.emit_nowait(
                StatusEvent(
                    type=StatusType.READY,
                    source=AvatarModule.AVATAR_ENGINE,
                    stage="session_ready",
                )
            )

    async def on_exit(self) -> None:
        errors: list[Exception] = []

        wait_pending = getattr(
            getattr(self._chat_ctx, "items", None),
            "wait_pending",
            None,
        )

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
            "avatar runtime shutdown",
            self._runtime.aclose,
            errors,
        )

        await self._run_shutdown_step(
            "session user path migration flush",
            lambda: self._runtime.session.flush_user_path_migrations(
                remove_old=True,
            ),
            errors,
        )

        if errors:
            raise ExceptionGroup(
                "AvatarEngine shutdown completed with errors.",
                errors,
            )

    """Node Op"""

    def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk | str | FlushSentinel]:
        async def _generate():
            turn_snapshot = self._ensure_turn_snapshot(chat_ctx)

            base_input = self._livekit_model_input.from_chat_context(
                chat_ctx,
                deferred_message_ids={turn_snapshot.input_id},
            )
            context = self._context_manager.build(
                base_input,
                turn_snapshot=turn_snapshot,
            )
            transport_input = self._livekit_model_input.to_chat_context(context.model_input)

            model_call_status = AvatarContextStatus(
                runtime=self._runtime,
                emitter=self._status,
                input_kind=context.input_kind,
            )
            await model_call_status.start()

            assistant_output_id = uuid4().hex
            assistant_text_started = False

            try:
                async for chunk in Agent.default.llm_node(
                    self,
                    transport_input,
                    tools,
                    model_settings,
                ):
                    await model_call_status.on_chunk(chunk)
                    text = extract_answer_text(chunk)
                    if text is not None:
                        assistant_text_started = True

                        # During the migration period this mirrors the text stream.
                        # AgentSession still performs the actual final TTS.
                        await self._runtime.output.publish_text_chunk(
                            text=text,
                            output_id=assistant_output_id,
                            turn_id=model_call_status.turn_id,
                            lane=OutputLane.ASSISTANT,
                        )

                    yield chunk

            finally:
                if assistant_text_started:
                    await self._runtime.output.complete(
                        lane=OutputLane.ASSISTANT,
                        output_id=assistant_output_id,
                        turn_id=model_call_status.turn_id,
                    )

                await model_call_status.close()

        return _generate()
