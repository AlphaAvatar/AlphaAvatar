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

from collections.abc import Sequence
from dataclasses import dataclass
from types import MethodType
from typing import TYPE_CHECKING, Any, Literal

from livekit.agents import ModelSettings, llm
from livekit.agents.voice import SpeechHandle

if TYPE_CHECKING:
    from ..engine import AvatarEngine


@dataclass
class Context:
    mode: Literal["pipeline", "realtime"]
    speech_handle: Any
    chat_ctx: llm.ChatContext
    tools: list[llm.FunctionTool | llm.RawFunctionTool]
    model_settings: ModelSettings
    new_message: Any | None = None
    instructions: str | None = None
    tools_messages: Sequence[llm.ChatItem] | None = None


class ContextSearch:
    def __init__(self, engine: AvatarEngine) -> None:
        self._engine = engine

    async def memory_search(self, ctx: Context) -> None:
        if ctx.chat_ctx:
            chat_context = ctx.chat_ctx.copy()
            if ctx.new_message is not None:
                chat_context.insert(ctx.new_message)
                await self._engine.memory.search_by_context(
                    avatar_id=self._engine.avatar_config.avatar_info.avatar_id,
                    session_id=self._engine.session_config.session_id,
                    chat_context=chat_context.items,
                )

    async def __call__(self, ctx: Context) -> None:
        # Perform context search based on mode
        await self.memory_search(ctx)


def install_context_search_patch(engine: AvatarEngine) -> None:
    """Patch the AgentActivity inside the engine to run hooks before reply tasks."""
    activity = engine._get_activity_or_raise()

    context_search = ContextSearch(engine)

    # --- pipeline --- #
    _orig_pipeline = activity._pipeline_reply_task

    async def _wrapped_pipeline(
        _self,
        *,
        speech_handle: SpeechHandle,
        chat_ctx: llm.ChatContext,
        tools: list[llm.FunctionTool | llm.RawFunctionTool],
        model_settings: ModelSettings,
        new_message: llm.ChatMessage | None = None,
        instructions: str | None = None,
        _tools_messages: Sequence[llm.FunctionCall | llm.FunctionCallOutput] | None = None,
    ):
        ro = Context(
            mode="pipeline",
            speech_handle=speech_handle,
            chat_ctx=chat_ctx,
            tools=tools,
            model_settings=model_settings,
            new_message=new_message,
            instructions=instructions,
            tools_messages=_tools_messages,
        )
        await context_search(ro)
        return await _orig_pipeline(
            speech_handle=speech_handle,
            chat_ctx=chat_ctx,
            tools=tools,
            model_settings=model_settings,
            new_message=new_message,
            instructions=instructions,
            _tools_messages=_tools_messages,
        )

    activity._pipeline_reply_task = MethodType(_wrapped_pipeline, activity)
