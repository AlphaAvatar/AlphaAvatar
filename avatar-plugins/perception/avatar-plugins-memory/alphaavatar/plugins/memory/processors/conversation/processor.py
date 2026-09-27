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
from collections.abc import Iterable
from typing import TYPE_CHECKING

from alphaavatar.agents.memory.enums import (
    MemoryCacheType,
    MemoryKind,
    MemoryType,
)
from alphaavatar.agents.memory.schemas import (
    MemoryItem,
    MemoryOwnerRef,
    MemoryScope,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import (
    AvatarCapabilityName,
    avatar_capability,
)
from alphaavatar.agents.utils.time import application_now

from ...log import logger
from ...state import MemoryContextState
from ..base import MemoryProcessor
from .config import ConversationConfig
from .consolidation import MemoryConsolidator
from .provider import ConversationProvider

if TYPE_CHECKING:
    from ...runtime import MemoryRuntime


@avatar_capability(
    name=AvatarCapabilityName.MEMORY_CONVERSATION,
    description=(
        "Can retain and recall relevant information learned from conversations across sessions."
    ),
)
class ConversationProcessor(MemoryProcessor):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        memory: MemoryRuntime,
        config: ConversationConfig,
    ) -> None:
        super().__init__(
            runtime=runtime,
            memory=memory,
        )

        self._config = config
        self._provider = ConversationProvider(config.provider)
        self._locks: dict[str, asyncio.Lock] = {}

        self._consolidator = MemoryConsolidator(
            config.pipeline,
            candidate_search=self._candidate_search,
            plan=self._provider.plan_consolidation,
        )

    @property
    def name(self) -> str:
        return "conversation"

    def _lock(self, context_id: str) -> asyncio.Lock:
        return self._locks.setdefault(
            context_id,
            asyncio.Lock(),
        )

    def record_recall(self, records: Iterable[MemoryItem]) -> None:
        self._consolidator.record_recall(records)

    async def _candidate_search(
        self,
        texts: list[str],
        *,
        owner_refs,
        context,
        timeout: float = 5.0,
    ):
        try:
            return await self.store.search_similar_batch(
                texts,
                owner_refs=owner_refs,
                context=context,
                memory_type=MemoryType.CONVERSATION,
                kind=MemoryKind.CONSOLIDATED,
                top_k=(self._config.pipeline.maintenance.max_candidates_per_item),
                timeout=timeout,
            )

        except Exception:
            logger.exception("[Memory] conversation consolidation candidate search failed")
            return [[] for _ in texts]

    async def update(self, state: MemoryContextState) -> None:
        if state.cache_type is not MemoryCacheType.SESSION_INTERACTION:
            return

        async with self._lock(state.context_id):
            start, end, messages = await self.checkpoint_window(state)

            if start == end:
                return

            content = self.render_context_content(
                state,
                messages,
            )

            delta = await self._provider.extract(
                context_content=content,
                session_gate=self._config.pipeline.extraction.session_gate,
                metadata=self.trace_metadata(
                    state=state,
                    component="conversation",
                    operation="conversation_delta",
                    memory_type=MemoryType.CONVERSATION,
                ),
            )

            source_refs = self.source_refs(messages)

            avatar_items = self.build_memory_items(
                state=state,
                memory_type=MemoryType.Avatar,
                patches=delta.assistant_memory_entries,
                owner_refs=[MemoryOwnerRef.avatar(self.avatar_id)],
                participant_refs=state.participant_refs,
                source_refs=source_refs,
                scope=MemoryScope.owner(),
            )

            conversation_items = self.build_memory_items(
                state=state,
                memory_type=MemoryType.CONVERSATION,
                patches=delta.user_or_tool_memory_entries,
                owner_refs=state.owner_refs,
                participant_refs=state.participant_refs,
                source_refs=source_refs,
                scope=MemoryScope.owner(),
            )

            conversation_items = await self._consolidator.consolidate_session(
                conversation_items,
                session_content=content,
                updated_at=application_now(),
                trace_metadata=(
                    self.trace_metadata(
                        state=state,
                        component="conversation.consolidation",
                        operation="memory_consolidation",
                        memory_type=MemoryType.CONVERSATION,
                    )
                ),
            )

            await self.commit_items(
                state=state,
                start=start,
                end=end,
                items=[
                    *avatar_items,
                    *conversation_items,
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
                if state.cache_type is MemoryCacheType.SESSION_INTERACTION
            )
        )
