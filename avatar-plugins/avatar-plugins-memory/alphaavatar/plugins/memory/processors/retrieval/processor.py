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
from collections.abc import (
    Callable,
    Iterable,
)
from typing import TYPE_CHECKING

from livekit.agents.llm import ChatItem

from alphaavatar.agents import AvatarModule
from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.memory.schemas import MemoryItem
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import (
    AvatarCapabilityName,
    avatar_capability,
)

from ...log import logger
from ...storage.graph import GraphLookup
from ...template import MemoryPluginsTemplate
from ..base import MemoryProcessor
from .config import RetrievalConfig
from .schema import RetrievalCapabilityInput

if TYPE_CHECKING:
    from ...runtime import MemoryRuntime

RecallObserver = Callable[
    [Iterable[MemoryItem]],
    None,
]


@avatar_capability(
    name=AvatarCapabilityName.MEMORY_RETRIEVAL,
    description=(
        "Search persistent memory when the currently retrieved runtime context "
        "is insufficient. Supports semantic text search and graph-linked retrieval "
        "over memories visible to the current owner and context, including prior "
        "decisions, preferences, tool outcomes, environment observations, and "
        "related entities."
    ),
    input_schema=RetrievalCapabilityInput,
)
class RetrievalProcessor(MemoryProcessor):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        memory: MemoryRuntime,
        config: RetrievalConfig,
        search_context: int,
        recall_num: int,
        recall_observers: tuple[
            RecallObserver,
            ...,
        ] = (),
    ) -> None:
        super().__init__(runtime=runtime, memory=memory)

        self._config = config
        self._search_context = search_context
        self._recall_num = recall_num
        self._recall_observers = recall_observers

    @property
    def name(self) -> str:
        return "retrieval"

    def _graph_lookup(self) -> GraphLookup:
        return GraphLookup(self.runtime.workspace.graph.namespace(AvatarModule.MEMORY.value).root)

    def _resolve_graph_keys(
        self,
        node_key: str,
        max_hops: int,
    ) -> list[str]:
        lookup = self._graph_lookup()
        resolved = lookup.resolve_keys(node_key)

        if max_hops <= 0:
            return resolved

        return lookup.expand_node_keys(
            node_keys=resolved,
            max_hops=max_hops,
            max_neighbors_per_node=16,
            min_weight=0.0,
        )

    def _notify_passive_recall(self, items: list[MemoryItem]) -> None:
        for observer in self._recall_observers:
            observer(items)

    async def search_text(
        self,
        query: str,
        *,
        context_id: str | None = None,
        memory_type: MemoryType | None = None,
        top_k: int | None = None,
        timeout: float | None = None,
    ) -> list[MemoryItem]:
        query = query.strip()

        if not query:
            return []

        state = self.memory_runtime.context_state(context_id or self.memory_runtime.root_context_id)

        owners = self.memory_runtime.recall_owners(state.owner_refs)

        try:
            return await self.memory_runtime.store.recall_by_context(
                context_str=query,
                owner_refs=owners,
                context=state.context,
                memory_type=memory_type,
                top_k=(top_k if top_k is not None else self._recall_num),
                timeout=(timeout if timeout is not None else 3.0),
            )

        except Exception as exc:
            logger.warning(
                "Memory text recall failed context=%s: %s",
                state.context_id,
                exc,
            )
            return []

    async def search_context(
        self,
        *,
        context_id: str,
        chat_context: list[ChatItem],
        timeout: float = 3.0,
    ) -> None:
        query = MemoryPluginsTemplate.apply_search_template(
            chat_context[-self._search_context :],
            filter_roles=["system"],
        )

        if not query:
            return

        items = await self.search_text(
            query,
            context_id=context_id,
            top_k=self._recall_num,
            timeout=timeout,
        )

        # Only passive recall contributes to the
        # conversation consolidation recall ledger.
        self._notify_passive_recall(items)
        self.memory_runtime.apply_items(items)

    async def search_graph(
        self,
        *,
        node_key: str | None = None,
        node_query: str | None = None,
        context_id: str | None = None,
        memory_type: MemoryType | None = None,
        node_type: str | None = None,
        max_hops: int = 0,
        top_k: int = 50,
        timeout: float | None = None,
    ) -> list[MemoryItem]:
        state = self.memory_runtime.context_state(context_id or self.memory_runtime.root_context_id)

        owners = self.memory_runtime.recall_owners(state.owner_refs)

        node_keys: list[str] = []

        if node_key:
            node_keys = await asyncio.to_thread(
                self._resolve_graph_keys,
                node_key,
                max_hops,
            )

        try:
            return await self.memory_runtime.store.recall_by_graph_node(
                owner_refs=owners,
                context=state.context,
                node_keys=node_keys,
                node_query=node_query,
                memory_type=memory_type,
                node_type=node_type,
                top_k=top_k,
                timeout=(timeout if timeout is not None else 3.0),
            )

        except Exception as exc:
            logger.warning(
                "Memory graph recall failed context=%s: %s",
                state.context_id,
                exc,
            )
            return []
