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
from collections import deque
from collections.abc import (
    Callable,
    Iterable,
)
from typing import TYPE_CHECKING

from alphaavatar.agents import AvatarModule
from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.memory.schemas import (
    MemoryItem,
    MemoryOwnerRef,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import (
    AvatarCapabilityName,
    avatar_capability,
)
from alphaavatar.core.turn import TurnInputModality, TurnSnapshot

from ...log import logger
from ...storage.graph import GraphLookup
from ..base import MemoryProcessor
from .config import RetrievalConfig
from .schema import RetrievalCapabilityInput, RetrievalOp

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
    TURN_CONSUMER_ID = "memory.retrieval.turn"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        memory: MemoryRuntime,
        config: RetrievalConfig,
        recall_observers: tuple[
            RecallObserver,
            ...,
        ] = (),
    ) -> None:
        super().__init__(runtime=runtime, memory=memory)

        self._config = config
        self._search_context = config.search_context
        self._recall_num = config.recall_num
        self._recall_observers = recall_observers

        self._consumer_task: asyncio.Task[None] | None = None
        self._query_history: dict[str, deque[str]] = {}

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

    def _recall_owners(self, owner_refs: list[MemoryOwnerRef]) -> list[MemoryOwnerRef]:
        return self.deduplicate_refs([MemoryOwnerRef.avatar(self.avatar_id), *owner_refs])

    async def _search_text(
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

        owners = self._recall_owners(state.owner_refs)

        try:
            return await self.store.recall_by_context(
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

    async def _search_graph(
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

        owners = self._recall_owners(state.owner_refs)

        node_keys: list[str] = []

        if node_key:
            node_keys = await asyncio.to_thread(
                self._resolve_graph_keys,
                node_key,
                max_hops,
            )

        try:
            return await self.store.recall_by_graph_node(
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

    """Processor invoke"""

    async def invoke(self, request: RetrievalCapabilityInput) -> str:
        match request.op:
            case RetrievalOp.TEXT_SEARCH:
                items = await self._search_text(request.query or "", top_k=request.top_k)
            case RetrievalOp.GRAPH_SEARCH:
                items = await self._search_graph(
                    node_key=request.node_key,
                    node_query=request.node_query,
                    node_type=request.node_type,
                    max_hops=request.max_hops,
                    top_k=request.top_k,
                )
            case _:
                raise ValueError(f"Unsupported retrieval operation: {request.op}")

        return "\n".join(item.render_line() for item in items) or "No relevant memory was found."

    """Processor Loop"""

    def _turn_query(self, snapshot: TurnSnapshot, context_id: str) -> str:
        text = (snapshot.text or "").strip()
        if not text:
            return ""

        history = self._query_history.setdefault(
            context_id,
            deque(maxlen=max(1, self._search_context)),
        )
        history.append(text)
        return "\n\n".join(f"### user:\n{item}" for item in history)

    async def _process_turn(self, snapshot: TurnSnapshot) -> None:
        if snapshot.modality == TurnInputModality.SYSTEM:
            return

        context_id = self.memory_runtime.resolve_context_id(snapshot.context_ids)
        if context_id is None:
            logger.warning(
                "Memory retrieval has no context for turn turn_id=%s context_ids=%s",
                snapshot.turn_id,
                snapshot.context_ids,
            )
            return

        query = self._turn_query(snapshot, context_id)
        if not query:
            return

        items = await self._search_text(
            query,
            context_id=context_id,
            top_k=self._recall_num,
        )

        self._notify_passive_recall(items)
        self.memory_runtime.apply_items(items)

    async def _consume_loop(self) -> None:
        stream = self.runtime.turn.events

        while True:
            try:
                await stream.wait_for_pending(consumer_id=self.TURN_CONSUMER_ID)
                batch = stream.read_pending(consumer_id=self.TURN_CONSUMER_ID, limit=1)

                if batch.has_gap:
                    logger.warning(
                        "Memory retrieval missed committed turns missed=%s",
                        batch.missed_count,
                    )

                if not batch.items:
                    stream.commit(consumer_id=self.TURN_CONSUMER_ID, cursor_seq=batch.cursor_seq)
                    continue

                await self._process_turn(batch.items[0].snapshot)
                stream.commit(consumer_id=self.TURN_CONSUMER_ID, cursor_seq=batch.cursor_seq)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Memory retrieval turn consumer failed")
                await asyncio.sleep(0.05)

    """Runtime operations"""

    async def _start(self) -> None:
        self.runtime.turn.register_context_consumer(self.TURN_CONSUMER_ID)
        self._consumer_task = asyncio.create_task(
            self._consume_loop(),
            name="memory_retrieval_turn_consumer",
        )

    async def _stop(self, *, finalize: bool) -> None:
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            await asyncio.gather(self._consumer_task, return_exceptions=True)
            self._consumer_task = None

        self.runtime.turn.events.clear_consumer(self.TURN_CONSUMER_ID)
        self.runtime.turn.unregister_context_consumer(self.TURN_CONSUMER_ID)
        self._query_history.clear()
