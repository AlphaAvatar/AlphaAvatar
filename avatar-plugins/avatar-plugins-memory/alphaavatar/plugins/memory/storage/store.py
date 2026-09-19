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
import json
import os
from typing import Any

from alphaavatar.agents import AvatarModule
from alphaavatar.agents.memory import MemoryStoreBackend
from alphaavatar.agents.memory.enums import (
    MemoryKind,
    MemoryOutboxTarget,
    MemoryType,
    VectorRunnerOP,
)
from alphaavatar.agents.memory.schemas import (
    MemoryCheckpointAdvance,
    MemoryCommitResult,
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryScope,
    MemorySearchHit,
)
from alphaavatar.agents.runtime import AvatarRuntime

from .export import MemoryExportSink
from .index_serialization import serialize_memory_items
from .outbox import MemoryOutboxWorker
from .sqlite import SQLiteMemoryStore


class MemoryStore:
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        backend: MemoryStoreBackend | None = None,
    ) -> None:
        memory_paths = runtime.workspace.data.memory
        graph_paths = runtime.workspace.graph.namespace(AvatarModule.MEMORY.value)

        self._runtime = runtime
        self._backend = backend or SQLiteMemoryStore(memory_paths.records_file)

        export_sink = MemoryExportSink(
            export_dir=memory_paths.exports.root,
            graph_dir=graph_paths.root,
        )

        self._outbox_workers = (
            MemoryOutboxWorker(
                backend=self._backend,
                target=MemoryOutboxTarget.INDEX,
                handler=self._index_items,
            ),
            MemoryOutboxWorker(
                backend=self._backend,
                target=MemoryOutboxTarget.EXPORT,
                handler=export_sink,
            ),
        )
        self._started = False

    @property
    def vdb_inference_method(self) -> str:
        method = os.getenv("MEMORY_VDB_INFERENCE_METHOD")
        if not method:
            raise RuntimeError("MEMORY_VDB_INFERENCE_METHOD is not configured")
        return method

    async def _infer(
        self,
        *,
        op: VectorRunnerOP,
        param: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        result = await asyncio.wait_for(
            self._runtime.inference.do_inference(
                self.vdb_inference_method,
                json.dumps(
                    {
                        "op": op,
                        "param": param,
                    }
                ).encode(),
            ),
            timeout=timeout,
        )

        if result is None:
            raise RuntimeError(f"Memory VDB returned no result op={op}")

        data = json.loads(result.decode())

        if error := data.get("error"):
            raise RuntimeError(f"Memory VDB {op} failed: {error}")

        return data

    @staticmethod
    def _owner_keys(owner_refs: list[MemoryOwnerRef]) -> list[str]:
        return list(dict.fromkeys(ref.key for ref in owner_refs))

    @staticmethod
    def _scope_keys(context: MemoryContextRef) -> list[str]:
        return list(MemoryScope.applicable_keys(context))

    @staticmethod
    def _candidate_ids(
        candidates: list[dict[str, Any]],
    ) -> list[str]:
        return list(
            dict.fromkeys(
                memory_id
                for candidate in candidates
                if (memory_id := str(candidate.get("memory_id") or "").strip())
            )
        )

    async def _index_items(self, items: list[MemoryItem]) -> None:
        if items:
            await self._infer(
                op=VectorRunnerOP.save,
                param={"memory_items": serialize_memory_items(items)},
                timeout=15.0,
            )

    async def recall_by_context(
        self,
        *,
        context_str: str,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
        top_k: int,
        timeout: float = 3.0,
    ) -> list[MemoryItem]:
        if top_k <= 0 or not context_str.strip() or not owner_refs:
            return []

        data = await self._infer(
            op=VectorRunnerOP.search_by_context,
            param={
                "context_str": context_str,
                "owner_keys": self._owner_keys(owner_refs),
                "scope_keys": self._scope_keys(context),
                "top_k": max(top_k * 3, top_k),
            },
            timeout=timeout,
        )

        memory_ids = self._candidate_ids(data.get("candidates") or [])

        if not memory_ids:
            return []

        memories = await self._backend.resolve_current(
            memory_ids,
            owner_refs=owner_refs,
            context=context,
        )

        return memories[:top_k]

    async def recall_by_graph_node(
        self,
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
        node_keys: list[str] | None = None,
        node_query: str | None = None,
        memory_type: MemoryType | None = None,
        node_type: str | None = None,
        top_k: int = 50,
        timeout: float = 3.0,
    ) -> list[MemoryItem]:
        if top_k <= 0 or not owner_refs:
            return []

        data = await self._infer(
            op=VectorRunnerOP.search_by_graph_node,
            param={
                "node_keys": node_keys or [],
                "node_query": node_query,
                "owner_keys": self._owner_keys(owner_refs),
                "scope_keys": self._scope_keys(context),
                "memory_type": (memory_type.value if memory_type is not None else None),
                "node_type": node_type,
                "top_k": max(top_k * 3, top_k),
            },
            timeout=timeout,
        )

        memory_ids = self._candidate_ids(data.get("candidates") or [])

        if not memory_ids:
            return []

        memories = await self._backend.resolve_current(
            memory_ids,
            owner_refs=owner_refs,
            context=context,
        )

        return memories[:top_k]

    async def search_consolidation_candidates(
        self,
        texts: list[str],
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
        top_k: int,
        timeout: float = 5.0,
    ) -> list[list[MemorySearchHit]]:
        if not texts:
            return []

        if top_k <= 0 or not owner_refs:
            return [[] for _ in texts]

        data = await self._infer(
            op=VectorRunnerOP.search_similar_batch,
            param={
                "texts": texts,
                "top_k": top_k,
                "owner_keys": self._owner_keys(owner_refs),
                "scope_keys": self._scope_keys(context),
                "memory_type": (MemoryType.CONVERSATION.value),
                "layer": (MemoryKind.CONSOLIDATED.value),
            },
            timeout=timeout,
        )

        results = data.get("results") or []

        if len(results) != len(texts):
            raise RuntimeError(
                f"Memory VDB candidate count mismatch: got {len(results)}, want {len(texts)}"
            )

        all_ids = self._candidate_ids([candidate for hits in results for candidate in hits])

        if not all_ids:
            return [[] for _ in texts]

        visible = await self._backend.get_visible(
            all_ids,
            owner_refs=owner_refs,
            context=context,
        )

        by_id = {memory.memory_id: memory for memory in visible}

        return [
            [
                MemorySearchHit(
                    memory=by_id[memory_id],
                    score=float(candidate.get("score") or 0.0),
                )
                for candidate in hits
                if (memory_id := str(candidate.get("memory_id") or "").strip()) in by_id
            ]
            for hits in results
        ]

    async def commit(
        self,
        items: list[MemoryItem],
        *,
        context_id: str,
        processor: str,
        idempotency_key: str,
        checkpoint: MemoryCheckpointAdvance | None = None,
    ) -> MemoryCommitResult:
        result = await self._backend.commit(
            items,
            context_id=context_id,
            processor=processor,
            idempotency_key=idempotency_key,
            checkpoint=checkpoint,
        )

        if result.memory_ids:
            for worker in self._outbox_workers:
                worker.wake()

        return result

    async def get_many(
        self,
        memory_ids: list[str],
    ) -> list[MemoryItem]:
        return await self._backend.get_many(memory_ids)

    async def get_visible(
        self,
        memory_ids: list[str],
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
    ) -> list[MemoryItem]:
        return await self._backend.get_visible(
            memory_ids,
            owner_refs=owner_refs,
            context=context,
        )

    async def resolve_current(
        self,
        memory_ids: list[str],
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
    ) -> list[MemoryItem]:
        return await self._backend.resolve_current(
            memory_ids,
            owner_refs=owner_refs,
            context=context,
        )

    async def query_visible(
        self,
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
        memory_type: MemoryType | None = None,
        kind: MemoryKind | None = None,
        limit: int = 100,
    ) -> list[MemoryItem]:
        return await self._backend.query_visible(
            owner_refs=owner_refs,
            context=context,
            memory_type=memory_type,
            kind=kind,
            limit=limit,
        )

    async def get_checkpoint(
        self,
        *,
        context_id: str,
        processor: str,
    ) -> int:
        return await self._backend.get_checkpoint(
            context_id=context_id,
            processor=processor,
        )

    async def start(self) -> None:
        if self._started:
            return

        await self._backend.initialize()

        for worker in self._outbox_workers:
            worker.start()

        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return

        await asyncio.gather(*(worker.stop() for worker in reversed(self._outbox_workers)))
        self._started = False
