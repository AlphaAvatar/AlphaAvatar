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

from livekit.agents.llm import ChatItem

from alphaavatar.agents.memory import MemoryPluginsTemplate
from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.memory.schemas import MemoryContextRef, MemoryItem, MemoryOwnerRef

from .log import logger


class MemoryRetrievalMixin:
    async def search_by_context(
        self,
        *,
        context_id: str,
        chat_context: list[ChatItem],
        timeout: float = 3.0,
    ) -> None:
        context_str = MemoryPluginsTemplate.apply_search_template(
            chat_context[-self.memory_search_context :],
            filter_roles=["system"],
        )
        if not context_str:
            logger.debug("Memory context recall skipped: empty query context=%s", context_id)
            return

        state = self._get_context_state_or_raise(context_id)
        owners = self._recall_owners(state.owner_refs)

        try:
            items = await self.store.recall_by_context(
                context_str=context_str,
                owner_refs=owners,
                context=state.context,
                top_k=self.memory_recall_num,
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("Memory context recall failed context=%s: %s", context_id, exc)
            return

        self._memory_consolidator.record_recall(items)
        self.avatar_memory = [item for item in items if item.memory_type is MemoryType.Avatar]
        self.user_memory = [item for item in items if item.memory_type is MemoryType.CONVERSATION]
        self.tool_memory = [item for item in items if item.memory_type is MemoryType.TOOLS]
        self.env_memory = [item for item in items if item.memory_type is MemoryType.ENV]
        logger.debug("Memory context recall context=%s resolved=%d", context_id, len(items))

    def _resolve_graph_keys(self, node_key: str, max_hops: int) -> list[str]:
        lookup = self._graph_lookup()
        resolved = lookup.resolve_keys(node_key)

        return (
            lookup.expand_node_keys(
                node_keys=resolved,
                max_hops=max_hops,
                max_neighbors_per_node=16,
                min_weight=0.0,
            )
            if max_hops > 0
            else resolved
        )

    async def search_by_graph_node(
        self,
        *,
        node_key: str | None = None,
        node_query: str | None = None,
        context_id: str | None = None,
        memory_type: MemoryType | None = None,
        node_type: str | None = None,
        max_hops: int = 0,
        top_k: int = 50,
        timeout: float = 3.0,
    ) -> list[MemoryItem]:
        context_id = context_id or self.root_context_id
        state = self._get_context_state_or_raise(context_id)
        owners = self._recall_owners(state.owner_refs)
        node_keys: list[str] = []

        if node_key:
            node_keys = await asyncio.to_thread(self._resolve_graph_keys, node_key, max_hops)

        try:
            return await self.store.recall_by_graph_node(
                owner_refs=owners,
                context=state.context,
                node_keys=node_keys,
                node_query=node_query,
                memory_type=memory_type,
                node_type=node_type,
                top_k=top_k,
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("Memory graph recall failed context=%s: %s", context_id, exc)
            return []

    async def _consolidation_candidate_search(
        self,
        texts: list[str],
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
        timeout: float = 5.0,
    ):
        try:
            return await self.store.search_consolidation_candidates(
                texts,
                owner_refs=owner_refs,
                context=context,
                top_k=self._pipeline_config.maintenance.max_candidates_per_item,
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("Memory consolidation candidate search failed: %s", exc)
            return [[] for _ in texts]

    def _recall_owners(self, owner_refs: list[MemoryOwnerRef]) -> list[MemoryOwnerRef]:
        refs = [MemoryOwnerRef.avatar(self.avatar_id), *owner_refs]
        return list({ref.key: ref for ref in refs}.values())
