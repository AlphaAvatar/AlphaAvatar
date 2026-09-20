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
from typing import TYPE_CHECKING

from livekit.agents.llm import (
    ChatItem,
    FunctionCall,
    FunctionCallOutput,
)

from alphaavatar.agents.memory.enums import (
    MemoryCacheType,
    MemoryType,
)
from alphaavatar.agents.memory.schemas import (
    MemoryOwnerRef,
    MemoryParticipantRef,
    MemoryScope,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import (
    AvatarCapabilityName,
    avatar_capability,
)

from ...state import MemoryContextState
from ..base import MemoryProcessor
from .config import ToolConfig
from .provider import ToolProvider

if TYPE_CHECKING:
    from ...runtime import MemoryRuntime


@avatar_capability(
    name=AvatarCapabilityName.MEMORY_TOOL,
    description=(
        "Can retain and recall useful information from previous tool interactions and results."
    ),
)
class ToolProcessor(MemoryProcessor):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        memory: MemoryRuntime,
        config: ToolConfig,
    ) -> None:
        super().__init__(
            runtime=runtime,
            memory=memory,
        )
        self._provider = ToolProvider(config.provider)
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def name(self) -> str:
        return "tool"

    def _lock(self, context_id: str) -> asyncio.Lock:
        return self._locks.setdefault(
            context_id,
            asyncio.Lock(),
        )

    @staticmethod
    def _has_tool_event(messages: list[ChatItem]) -> bool:
        return any(
            isinstance(
                item,
                FunctionCall | FunctionCallOutput,
            )
            or getattr(item, "tool_calls", None)
            or getattr(item, "function_call", None)
            or getattr(item, "type", None)
            in {
                "function_call",
                "function_call_output",
                "agent_config_update",
                "agent_handoff",
            }
            for item in messages
        )

    def _participants(
        self,
        state: MemoryContextState,
        messages: list[ChatItem],
    ) -> list[MemoryParticipantRef]:
        refs = list(state.participant_refs)

        refs.extend(
            MemoryParticipantRef.tool(tool_id)
            for item in messages
            if isinstance(
                item,
                FunctionCall | FunctionCallOutput,
            )
            and (tool_id := str(getattr(item, "name", "") or "").strip())
        )

        return self.deduplicate_refs(refs)

    async def update(self, state: MemoryContextState) -> None:
        if state.cache_type not in {
            MemoryCacheType.SESSION_INTERACTION,
            MemoryCacheType.AGENT_TOOL_INTERACTION,
        }:
            return

        async with self._lock(state.context_id):
            start, end, messages = await self.checkpoint_window(state)

            if start == end:
                return

            if not self._has_tool_event(messages):
                await self.commit_items(state=state, start=start, end=end, items=[])
                return

            content = self.render_context_content(
                state,
                messages,
            )

            delta = await self._provider.extract(
                context_content=content,
                metadata=self.trace_metadata(
                    state=state,
                    component="tool",
                    operation="tool_delta",
                    memory_type=MemoryType.TOOLS,
                ),
            )

            participants = self._participants(
                state,
                messages,
            )
            source_refs = self.source_refs(messages)

            avatar_items = self.build_memory_items(
                state=state,
                memory_type=MemoryType.Avatar,
                patches=delta.assistant_memory_entries,
                owner_refs=[MemoryOwnerRef.avatar(self.avatar_id)],
                participant_refs=participants,
                source_refs=source_refs,
                scope=MemoryScope.owner(),
            )

            tool_items = self.build_memory_items(
                state=state,
                memory_type=MemoryType.TOOLS,
                patches=delta.user_or_tool_memory_entries,
                owner_refs=state.owner_refs,
                participant_refs=participants,
                source_refs=source_refs,
                scope=MemoryScope.owner(),
            )

            await self.commit_items(
                state=state,
                start=start,
                end=end,
                items=[
                    *avatar_items,
                    *tool_items,
                ],
            )

    async def _stop(
        self,
        *,
        finalize: bool,
    ) -> None:
        if not finalize:
            return

        await asyncio.gather(
            *(
                self.update(state)
                for state in self.memory_runtime.memory_contexts.values()
                if state.cache_type
                in {
                    MemoryCacheType.SESSION_INTERACTION,
                    MemoryCacheType.AGENT_TOOL_INTERACTION,
                }
            )
        )
