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
"""Model-call context preparation and generation status coordination."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from livekit.agents import llm
from livekit.agents.types import FlushSentinel
from livekit.agents.voice.generation import update_instructions

from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE
from alphaavatar.agents.log import logger
from alphaavatar.agents.plugin import AvatarModule
from alphaavatar.agents.status import (
    StatusEmitter,
    StatusEvent,
    StatusType,
)
from alphaavatar.agents.utils import format_current_time

from .assembler import PromptAssembler
from .template import AvatarSysPromptTemplate, RuntimeContextTemplate

if TYPE_CHECKING:
    from alphaavatar.agents.memory import MemoryBase
    from alphaavatar.agents.persona import PersonaBase
    from alphaavatar.agents.runtime import ContextRuntime

    from ..vision import VisionBase


@dataclass(frozen=True, slots=True)
class PreparedModelCall:
    chat_ctx: llm.ChatContext
    input_kind: str | None


class AvatarModelContextBuilder:
    """Build the temporary model-facing context for one inference call."""

    def __init__(
        self,
        *,
        context_runtime: ContextRuntime,
        memory: MemoryBase,
        persona: PersonaBase,
        vision: VisionBase,
        system_template: AvatarSysPromptTemplate,
        runtime_context_template: RuntimeContextTemplate,
        prompt_assembler: PromptAssembler,
    ) -> None:
        self._context_runtime = context_runtime
        self._memory = memory
        self._persona = persona
        self._vision = vision
        self._system_template = system_template
        self._runtime_context_template = runtime_context_template
        self._prompt_assembler = prompt_assembler

    def prepare(self, chat_ctx: llm.ChatContext) -> PreparedModelCall:
        self._refresh_runtime_context()

        update_instructions(
            chat_ctx,
            instructions=self._system_template.instructions(
                stable_persona=self._context_runtime.user_persona,
            ),
            add_if_missing=True,
        )

        model_chat_ctx = self._prompt_assembler.prepare_model_chat_context(
            chat_ctx,
            strip_historical_visuals=True,
            add_visual_placeholder=True,
        )

        input_kind = latest_input_kind(model_chat_ctx)

        # Keep current behavior unchanged during this structural refactor.
        # Visual relevance gating can be implemented separately.
        self._vision.inject_into_chat_ctx(model_chat_ctx)

        runtime_context = self._runtime_context_template.render(
            context_runtime=self._context_runtime,
        )

        injected_chat_ctx = self._prompt_assembler.inject_runtime_context(
            model_chat_ctx,
            runtime_context=runtime_context,
        )

        return PreparedModelCall(
            chat_ctx=injected_chat_ctx,
            input_kind=input_kind,
        )

    def _refresh_runtime_context(self) -> None:
        context = self._context_runtime

        context.timestamp = format_current_time(
            context.timestamp.timezone,
            context.timestamp.timezone_source,
        )

        context.user_persona = self._persona.persona_content or DEFAULT_SYSTEM_VALUE
        context.memory_content = self._memory.memory_content or DEFAULT_SYSTEM_VALUE

        context.plan_content = context.plan_content or DEFAULT_SYSTEM_VALUE
        context.reflection_content = context.reflection_content or DEFAULT_SYSTEM_VALUE
        context.turn_behavior_rules = context.turn_behavior_rules or DEFAULT_SYSTEM_VALUE


class ModelCallStatus:
    def __init__(
        self,
        *,
        emitter: StatusEmitter,
        input_kind: str | None,
    ) -> None:
        self._emitter = emitter
        self._input_kind = input_kind

        self.turn_id: str | None = emitter.current_turn_id

        self._thinking_task: asyncio.Task | None = None
        self._finalizing_task: asyncio.Task | None = None
        self._answer_started = False

    async def start(self) -> None:
        if self._input_kind == "user":
            self.turn_id = await self._emitter.start_turn()

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


def latest_input_kind(chat_ctx: llm.ChatContext) -> str | None:
    for item in reversed(getattr(chat_ctx, "items", [])):
        role = getattr(item, "role", None)
        item_type = getattr(item, "type", None)

        if role == "user":
            return "user"

        if role in {"tool", "function"}:
            return "tool_output"

        if item_type in {
            "tool_result",
            "tool_output",
            "function_result",
            "function_output",
            "function_call_output",
        }:
            return "tool_output"

        if role is not None:
            return str(role)

    return None


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
