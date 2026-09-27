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
from uuid import uuid4

from livekit.agents import llm
from livekit.agents.types import FlushSentinel

from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.plugin import AvatarModule
from alphaavatar.agents.status import (
    StatusEmitter,
    StatusEvent,
    StatusType,
)


class AvatarContextStatus:
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        emitter: StatusEmitter,
        input_kind: str | None,
    ) -> None:
        self._runtime = runtime
        self._emitter = emitter
        self._input_kind = input_kind

        self.turn_id: str | None = emitter.current_turn_id

        self._thinking_task: asyncio.Task | None = None
        self._finalizing_task: asyncio.Task | None = None
        self._answer_started = False

    async def _cancel_task(self, attribute: str) -> None:
        task = getattr(self, attribute)
        setattr(self, attribute, None)

        if task is None:
            return

        if not task.done():
            task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug(
                "Delayed model-call status task failed: %s",
                exc,
            )

    async def start(self) -> None:
        if self._input_kind == "user":
            self.turn_id = uuid4().hex

            await self._runtime.output.start_turn(turn_id=self.turn_id)
            await self._emitter.start_turn(turn_id=self.turn_id)

            self._thinking_task = self._emitter.emit_delayed(
                StatusEvent(
                    type=StatusType.THINKING,
                    source=AvatarModule.AVATAR_ENGINE,
                    stage="thinking",
                ),
                delay_sec=1.5,
            )

        elif self._input_kind == "tool_output":
            self.turn_id = self._emitter.current_turn_id

            self._finalizing_task = self._emitter.emit_delayed(
                StatusEvent(
                    type=StatusType.FINALIZING,
                    source=AvatarModule.AVATAR_ENGINE,
                    stage="after_tool",
                ),
                delay_sec=1.2,
            )

    async def on_chunk(
        self,
        chunk: llm.ChatChunk | str | FlushSentinel,
    ) -> None:
        if not self._answer_started and is_answer_chunk(chunk):
            self._answer_started = True

            # Only cancel status events that have not been emitted yet.
            # OutputRuntime preempts already-emitted transient speech when
            # the first assistant text chunk enters the output stream.
            await self._cancel_task("_thinking_task")
            await self._cancel_task("_finalizing_task")
            return

        if self._finalizing_task is not None:
            await self._cancel_task("_finalizing_task")

    async def close(self) -> None:
        await self._cancel_task("_thinking_task")
        await self._cancel_task("_finalizing_task")


def extract_answer_text(chunk: llm.ChatChunk | str | FlushSentinel) -> str | None:
    if isinstance(chunk, str):
        text = chunk.strip()
        return text or None

    delta = getattr(chunk, "delta", None)
    if delta is None:
        return None

    tool_calls = getattr(delta, "tool_calls", None) or getattr(delta, "toolCalls", None)
    if tool_calls:
        return None

    content = getattr(delta, "content", None)
    if isinstance(content, str) and content:
        return content

    return None


def is_answer_chunk(chunk: llm.ChatChunk | str | FlushSentinel) -> bool:
    return extract_answer_text(chunk) is not None
