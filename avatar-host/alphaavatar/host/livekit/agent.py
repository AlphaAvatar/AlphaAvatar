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

import asyncio
from collections.abc import AsyncIterable, Sequence
from typing import TYPE_CHECKING
from uuid import uuid4

from livekit.agents import Agent, ModelSettings, llm
from livekit.agents.types import FlushSentinel

from alphaavatar.agents.avatar import AvatarEngine
from alphaavatar.agents.avatar.context.schemas import ContextPrepareRequest
from alphaavatar.agents.entrypoints.livekit import LiveKitModelInput, LiveKitTurnInput
from alphaavatar.core.lifecycle import SessionLifecycle
from alphaavatar.core.output.enums import OutputLane
from alphaavatar.core.turn import TurnInputModality, TurnSnapshot
from alphaavatar.host.lifecycle import HostSessionLifecycle

from .execution import LiveKitExecutionBridge, extract_answer_text
from .records import LiveKitOutputBridge
from .tools import build_function_tools

if TYPE_CHECKING:
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.runtime import AvatarRuntime


class LiveKitHostedAgent(AvatarEngine):
    """Temporary SDK model/hook bridge. Native Loop execution does not import this module."""

    def __init__(
        self,
        *,
        avatar_config: AvatarConfig,
        runtime: AvatarRuntime,
        inputs: Sequence[SessionLifecycle] = (),
        outputs: Sequence[SessionLifecycle] = (),
    ) -> None:
        self._livekit_model_input = LiveKitModelInput(clock=runtime.clock)
        self._livekit_turn_input = LiveKitTurnInput(clock=runtime.clock, runtime=runtime)
        self._execution_bridge = LiveKitExecutionBridge(runtime)
        super().__init__(
            avatar_config=avatar_config,
            runtime=runtime,
            tool_adapter=lambda registry: build_function_tools(
                registry, bridge=self._execution_bridge
            ),
        )
        self._output_bridge = LiveKitOutputBridge(
            output=runtime.output,
            adapter=self._livekit_model_input,
            context_id=runtime.state.context_id,
        )
        self._host_lifecycle = HostSessionLifecycle(engine=self, inputs=inputs, outputs=outputs)

    @property
    def host_lifecycle(self) -> HostSessionLifecycle:
        return self._host_lifecycle

    def _ensure_turn_snapshot(self, chat_ctx: llm.ChatContext) -> TurnSnapshot:
        message = self._livekit_turn_input.latest_user_message(chat_ctx)
        if message is not None:
            snapshot = self._runtime.turn.get(message.id)
            if snapshot is not None:
                return snapshot
        snapshot = self._livekit_turn_input.commit_chat_context(chat_ctx, source="livekit_llm_node")
        if snapshot is not None:
            return snapshot
        if self._runtime.turn.latest is not None:
            return self._runtime.turn.latest
        return self._runtime.turn.commit_input(
            input_id=f"system:{uuid4().hex}",
            modality=TurnInputModality.SYSTEM,
            context_ids=(self._runtime.state.context_id,),
            metadata={"source": "livekit_llm_node_system_trigger"},
        )

    def llm_node(
        self, chat_ctx: llm.ChatContext, tools: list[llm.Tool], model_settings: ModelSettings
    ) -> AsyncIterable[llm.ChatChunk | str | FlushSentinel]:
        async def generate():
            snapshot = self._ensure_turn_snapshot(chat_ctx)
            context_id = self._runtime.state.context_id
            step = self._execution_bridge.begin(
                self.session.current_speech, snapshot, context_id=context_id
            )
            output_id, text_started, completed = uuid4().hex, False, False
            try:
                if step.model_step == 1:
                    await self._runtime.output.start_turn(turn_id=snapshot.turn_id)
                base = self._livekit_model_input.from_chat_context(
                    chat_ctx, deferred_message_ids={snapshot.input_id}
                )
                model_input = await self._context_manager.prepare(
                    ContextPrepareRequest(
                        input=base,
                        input_id=snapshot.input_id,
                        turn_id=snapshot.turn_id,
                        context_id=context_id,
                    )
                )
                transport_input = self._livekit_model_input.to_chat_context(model_input)
                self._execution_bridge.model_started(step)
                async for chunk in Agent.default.llm_node(
                    self, transport_input, tools, model_settings
                ):
                    text = extract_answer_text(chunk)
                    if text is not None:
                        text_started = True
                        event = await self._runtime.output.publish_text_chunk(
                            text=text,
                            output_id=output_id,
                            turn_id=snapshot.turn_id,
                            lane=OutputLane.ASSISTANT,
                            run_id=step.scope.run_id,
                            metadata={"request_id": step.request_id, "context_id": context_id},
                        )
                        if event is not None:
                            self._execution_bridge.visible(step, output_id)
                    yield chunk
                completed = True
            except BaseException as exc:
                self._execution_bridge.model_failed(
                    step, cancelled=isinstance(exc, asyncio.CancelledError | GeneratorExit)
                )
                raise
            finally:
                if text_started:
                    if completed:
                        await self._runtime.output.complete(
                            lane=OutputLane.ASSISTANT, output_id=output_id, turn_id=snapshot.turn_id
                        )
                    else:
                        await self._runtime.output.interrupt(
                            output_id=output_id, reason="model_stream_stopped"
                        )

        return generate()

    async def on_session_start(self) -> None:
        await super().on_session_start()
        try:
            self._output_bridge.start(self.session)
        except BaseException:
            await super().on_session_stop()
            raise

    async def on_session_stop(self) -> None:
        errors: list[Exception] = []
        try:
            await self._execution_bridge.aclose()
        except Exception as exc:
            errors.append(exc)
        try:
            self._output_bridge.close()
        except Exception as exc:
            errors.append(exc)
        try:
            await super().on_session_stop()
        except Exception as exc:
            errors.append(exc)
        if errors:
            raise ExceptionGroup("Hosted Agent cleanup failed", errors)

    async def on_enter(self) -> None:
        await self._host_lifecycle.start()

    async def on_exit(self) -> None:
        await self._host_lifecycle.aclose()
