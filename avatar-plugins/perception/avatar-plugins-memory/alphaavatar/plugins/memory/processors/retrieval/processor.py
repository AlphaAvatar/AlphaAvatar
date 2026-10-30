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
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.memory.schemas import MemoryItem, MemoryOwnerRef
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import avatar_capability
from alphaavatar.agents.runtime.capability.enums import AvatarCapabilityName
from alphaavatar.agents.runtime.plugin import AvatarModule

from ...storage.graph import GraphLookup
from ..base import MemoryProcessor
from .config import RetrievalConfig
from .passive import PassiveRecall
from .schema import RetrievalCapabilityInput, RetrievalOp

if TYPE_CHECKING:
    from alphaavatar.core.turn.schemas import TurnSnapshot

    from ...runtime import MemoryRuntime
    from ...schemas import MemoryIdentitySnapshot
    from ...state import MemoryContextState

logger = logging.getLogger(__name__)

RecallObserver = Callable[[Iterable[MemoryItem]], None]


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
    TURN_CONSUMER_ID = PassiveRecall.CONSUMER_ID

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        memory: MemoryRuntime,
        config: RetrievalConfig,
        recall_observers: tuple[RecallObserver, ...] = (),
    ) -> None:
        super().__init__(runtime=runtime, memory=memory)

        self._config = config
        self._recall_num = config.recall_num
        self._recall_observers = recall_observers

        self._passive = PassiveRecall(
            runtime=runtime, memory=memory, config=config, notify=self._notify_passive_recall
        )

    @property
    def name(self) -> str:
        return "retrieval"

    def _graph_lookup(self) -> GraphLookup:
        return GraphLookup(self.runtime.workspace.graph.namespace(AvatarModule.MEMORY.value).root)

    def _resolve_graph_keys(self, node_key: str, max_hops: int) -> list[str]:
        lookup = self._graph_lookup()
        resolved = lookup.resolve_keys(node_key)

        if max_hops <= 0:
            return resolved

        return lookup.expand_node_keys(
            node_keys=resolved, max_hops=max_hops, max_neighbors_per_node=16, min_weight=0.0
        )

    def _notify_passive_recall(self, items: list[MemoryItem]) -> None:
        for observer in self._recall_observers:
            observer(items)

    def _recall_owners(self, owner_refs: list[MemoryOwnerRef]) -> list[MemoryOwnerRef]:
        return self.deduplicate_refs([MemoryOwnerRef.avatar(self.avatar_id), *owner_refs])

    def _recall_context(
        self, context_id: str | None, snapshot: TurnSnapshot | None
    ) -> tuple[MemoryContextState, MemoryIdentitySnapshot]:
        self.memory_runtime.sync_session()
        if snapshot is not None:
            context_id = context_id or self.memory_runtime.resolve_context_id(snapshot.context_ids)

        state = self.memory_runtime.context_state(context_id or self.memory_runtime.root_context_id)
        if snapshot is not None and (
            state.context_id not in snapshot.context_ids
            or (
                state.get_turn(snapshot.turn_id) is not snapshot
                and self.runtime.turn.get(snapshot.input_id) is not snapshot
            )
        ):
            raise ValueError("Memory retrieval requires the execution's committed Turn")
        return state, state.capture_identity(() if snapshot is None else (snapshot,))

    async def _search_text(
        self,
        query: str,
        *,
        context_id: str | None = None,
        memory_type: MemoryType | None = None,
        top_k: int | None = None,
        timeout: float | None = None,
        snapshot: TurnSnapshot | None = None,
    ) -> list[MemoryItem]:
        query = query.strip()

        if not query:
            return []

        state, identity = self._recall_context(context_id, snapshot)
        if not self.memory_runtime.identity_is_current(identity):
            return []

        owners = self._recall_owners([] if identity.unattributed else list(identity.owner_refs))

        try:
            items = await self.store.recall_by_context(
                context_str=query,
                owner_refs=owners,
                context=state.context,
                memory_type=memory_type,
                top_k=(top_k if top_k is not None else self._recall_num),
                timeout=(timeout if timeout is not None else 3.0),
                participants=identity.participants,
            )
            return (
                self.memory_runtime.visible_items(items, identity=identity, context=state.context)
                if self.memory_runtime.identity_is_current(identity)
                else []
            )

        except Exception as exc:
            logger.warning("Memory text recall failed context=%s: %s", state.context_id, exc)
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
        snapshot: TurnSnapshot | None = None,
    ) -> list[MemoryItem]:
        state, identity = self._recall_context(context_id, snapshot)
        if not self.memory_runtime.identity_is_current(identity):
            return []

        owners = self._recall_owners([] if identity.unattributed else list(identity.owner_refs))

        node_keys: list[str] = []

        if node_key:
            node_keys = await asyncio.to_thread(self._resolve_graph_keys, node_key, max_hops)

        try:
            items = await self.store.recall_by_graph_node(
                owner_refs=owners,
                context=state.context,
                node_keys=node_keys,
                node_query=node_query,
                memory_type=memory_type,
                node_type=node_type,
                top_k=top_k,
                timeout=(timeout if timeout is not None else 3.0),
                participants=identity.participants,
            )
            return (
                self.memory_runtime.visible_items(items, identity=identity, context=state.context)
                if self.memory_runtime.identity_is_current(identity)
                else []
            )

        except Exception as exc:
            logger.warning("Memory graph recall failed context=%s: %s", state.context_id, exc)
            return []

    """Processor invoke"""

    async def invoke(
        self, request: RetrievalCapabilityInput, *, input_id: str | None = None
    ) -> str:
        if not input_id or (snapshot := self.runtime.turn.get(input_id)) is None:
            raise ValueError("Memory retrieval requires a committed input_id")

        match request.op:
            case RetrievalOp.TEXT_SEARCH:
                items = await self._search_text(
                    request.query or "", top_k=request.top_k, snapshot=snapshot
                )
            case RetrievalOp.GRAPH_SEARCH:
                items = await self._search_graph(
                    node_key=request.node_key,
                    node_query=request.node_query,
                    node_type=request.node_type,
                    max_hops=request.max_hops,
                    top_k=request.top_k,
                    snapshot=snapshot,
                )
            case _:
                raise ValueError(f"Unsupported retrieval operation: {request.op}")

        return "\n".join(item.render_line() for item in items) or "No relevant memory was found."

    """Runtime operations"""

    async def _start(self) -> None:
        if self._config.enabled:
            await self._passive.start()

    async def _stop(self, *, finalize: bool) -> None:
        await self._passive.stop()
