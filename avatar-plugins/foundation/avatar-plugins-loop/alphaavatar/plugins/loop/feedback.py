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
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from alphaavatar.agents.avatar.loop.enums import LoopState
from alphaavatar.agents.avatar.loop.schemas import LoopIdentity
from alphaavatar.agents.avatar.provider.enums import ModelMessagePhase
from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas import (
    ModelInputMessage,
    ModelRefusalPart,
    ModelTextPart,
)
from alphaavatar.agents.avatar.provider.schemas.stream import ModelTextDelta
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvOutput
from alphaavatar.core.log.events import log_event
from alphaavatar.core.output.enums import (
    ExecutionSignalKind,
    OutputKind,
    OutputLane,
    OutputTextMode,
)
from alphaavatar.core.output.enums.message_phase import OutputMessagePhase
from alphaavatar.core.output.schemas import (
    OutputExecutionSignal,
    OutputScope,
    OutputSource,
    OutputTextChunk,
)

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime

logger = logging.getLogger(__name__)


class LoopDeliveryError(RuntimeError):
    pass


@dataclass(slots=True)
class _Message:
    output_id: str
    item_id: str
    text: str = ""
    content_index: int = -1
    completed: bool = False
    phase: ModelMessagePhase | None = None


class LoopFeedback:
    """Execution facts are synchronous journal writes; only user content awaits delivery."""

    def __init__(
        self,
        identity: LoopIdentity,
        runtime: AvatarRuntime,
        *,
        timeout: float,
        reasoning_effort: str | None = None,
        query_difficulty: str | None = None,
    ) -> None:
        self.identity = identity
        self.scope = OutputScope(identity.context_id, identity.turn_id, identity.run_id)
        self.state, self.model_step, self.tool_round = LoopState.ACCEPTED, 0, 0
        self._output = runtime.output
        self._session_id = runtime.session.session_id
        interaction = runtime.state.interaction_method
        self._mode = (
            OutputTextMode.AUDIO_SYNCED
            if interaction.audio_output
            else OutputTextMode.IMMEDIATE
            if interaction.text_output
            else OutputTextMode.MIRROR
        )
        self._timeout = timeout
        self._reasoning_effort, self._query_difficulty = reasoning_effort, query_difficulty
        self._messages: dict[str, _Message] = {}
        self._commentary: dict[str, None] = {}
        self._request_id: str | None = None
        self._close_task: asyncio.Task[None] | None = None

    def output_id(self, item_id: str) -> str:
        return f"{self.identity.run_id}:{item_id}"

    def signal(self, kind: ExecutionSignalKind, **fields) -> None:
        try:
            self._output.publish_execution(
                OutputExecutionSignal(
                    scope=self.scope,
                    kind=kind,
                    state=self.state.value,
                    model_step=self.model_step,
                    tool_round=self.tool_round,
                    request_id=self._request_id,
                    commentary_output_ids=tuple(self._commentary),
                    reasoning_effort=self._reasoning_effort,
                    query_difficulty=self._query_difficulty,
                    **fields,
                )
            )
        except Exception:
            logger.exception("Execution observation publication failed kind=%s", kind)
        else:
            if kind in {ExecutionSignalKind.TOOL_STARTED, ExecutionSignalKind.TOOL_FINISHED}:
                log_event(
                    logger,
                    "tool.started" if kind == ExecutionSignalKind.TOOL_STARTED else "tool.finished",
                    session_id=self._session_id,
                    context_id=self.scope.context_id,
                    turn_id=self.scope.turn_id,
                    run_id=self.scope.run_id,
                    request_id=self._request_id,
                    call_id=fields.get("call_id"),
                    tool_name=fields.get("tool_name"),
                    outcome=fields.get("outcome"),
                    executed=fields.get("executed"),
                    reason=fields.get("reason"),
                )

    def begin_model(self, request_id: str) -> None:
        self._request_id = request_id
        self._commentary.clear()

    async def change(self, state: LoopState, *, reason: str | None = None) -> None:
        self.state = state
        kinds = {
            LoopState.ACCEPTED: ExecutionSignalKind.ACCEPTED,
            LoopState.MODEL: ExecutionSignalKind.MODEL_STARTED,
            LoopState.TOOLS: ExecutionSignalKind.TOOLS_PENDING,
            LoopState.FINALIZING: ExecutionSignalKind.FINALIZING,
        }
        self.signal(kinds[state], reason=reason)

    async def _text(self, message: _Message, text: str, *, content_index: int) -> None:
        if not text or not self._output.accepts_run(self.identity.run_id):
            return
        try:
            content = EnvOutput(
                kind=OutputKind.TEXT_CHUNK,
                lane=OutputLane.ASSISTANT,
                scope=self.scope,
                output_id=message.output_id,
                source=OutputSource("avatar.loop", self._request_id, message.item_id),
                payload=OutputTextChunk(
                    text=text,
                    mode=self._mode,
                    replace_lane=False,
                    phase=OutputMessagePhase(message.phase.value) if message.phase else None,
                    content_index=content_index,
                ),
            )

            async with asyncio.timeout(self._timeout):
                event = await self._output.publish(content)

            if event is not None:
                message.text += text
                if message.phase == ModelMessagePhase.COMMENTARY:
                    self._commentary[message.output_id] = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise LoopDeliveryError("Loop text publication failed") from exc

    def _phase(self, message: _Message, phase: ModelMessagePhase | None) -> None:
        if phase is not None:
            if message.phase is not None and message.phase != phase:
                raise ModelProtocolError("Assistant message phase changed")

            message.phase = phase
        if message.text and message.phase == ModelMessagePhase.COMMENTARY:
            self._commentary[message.output_id] = None

    async def text(self, event: ModelTextDelta) -> None:
        if not self._output.accepts_run(self.identity.run_id):
            return

        message = self._messages.setdefault(
            event.item_id, _Message(self.output_id(event.item_id), event.item_id, phase=event.phase)
        )

        self._phase(message, event.phase)
        if message.completed or event.content_index < message.content_index:
            raise ModelProtocolError("Text delta follows completed or out-of-order content")

        separator = "\n" if message.text and event.content_index > message.content_index else ""
        await self._text(message, separator + event.text, content_index=event.content_index)
        message.content_index = event.content_index

    async def message(self, item: ModelInputMessage) -> None:
        if not self._output.accepts_run(self.identity.run_id):
            return

        text = "\n".join(
            part.text for part in item.parts if isinstance(part, ModelTextPart | ModelRefusalPart)
        )
        if not text:
            return

        message = self._messages.setdefault(
            item.id, _Message(self.output_id(item.id), item.id, phase=item.phase)
        )
        self._phase(message, item.phase)
        if message.completed:
            if message.text != text:
                raise ModelProtocolError("Completed message changed after delivery")
            return
        if not text.startswith(message.text):
            raise ModelProtocolError("Completed message disagrees with streamed content")

        await self._text(
            message, text[len(message.text) :], content_index=max(message.content_index, 0)
        )
        try:
            async with asyncio.timeout(self._timeout):
                await self._output.finish_text(
                    output_id=message.output_id,
                    turn_id=self.identity.turn_id,
                    run_id=self.identity.run_id,
                )
                if self._mode != OutputTextMode.AUDIO_SYNCED:
                    await self._output.complete(
                        lane=OutputLane.ASSISTANT,
                        output_id=message.output_id,
                        turn_id=self.identity.turn_id,
                    )

            message.completed = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise LoopDeliveryError("Loop text completion failed") from exc

    async def interrupt_incomplete(self, reason: str) -> None:
        for message in self._messages.values():
            if message.text and not message.completed:
                await self._output.interrupt(output_id=message.output_id, reason=reason)

    async def aclose(self, *, interrupted: bool = False) -> None:
        if self._close_task is None:

            async def close() -> None:
                if interrupted:
                    self._output.revoke_run(self.identity.run_id)
                    for message in self._messages.values():
                        if message.text:
                            await self._output.interrupt(
                                output_id=message.output_id, reason="loop_stopped"
                            )
                else:
                    await self.interrupt_incomplete("source_incomplete")

            self._close_task = asyncio.create_task(close(), name="loop_output_close")
        await wait_for_cleanup(self._close_task)
