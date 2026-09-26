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
import pathlib
from collections.abc import Callable
from typing import Any, TypeVar

from alphaavatar.agents.memory import MemoryStoreBackend
from alphaavatar.agents.memory.enums import (
    MemoryKind,
    MemoryOutboxTarget,
    MemoryType,
)
from alphaavatar.agents.memory.schemas import (
    MemoryCheckpointAdvance,
    MemoryCommitResult,
    MemoryContextRef,
    MemoryItem,
    MemoryOutboxEvent,
    MemoryOwnerRef,
)

from .commit import commit_sync
from .database import initialize_database
from .outbox import (
    claim_outbox_sync,
    complete_outbox_sync,
    retry_outbox_sync,
)
from .query import (
    get_checkpoint_sync,
    get_many_sync,
    get_visible_sync,
    query_visible_sync,
)
from .resolution import resolve_current_sync

T = TypeVar("T")


class SQLiteMemoryStore(MemoryStoreBackend):
    def __init__(self, path: pathlib.Path) -> None:
        self._path = path
        self._write_lock = asyncio.Lock()
        self._initialized = False

    async def _run_read(
        self,
        fn: Callable[..., T],
        *args: Any,
    ) -> T:
        return await asyncio.to_thread(fn, *args)

    async def _run_write(
        self,
        fn: Callable[..., T],
        *args: Any,
    ) -> T:
        async with self._write_lock:
            task = asyncio.create_task(asyncio.to_thread(fn, *args))

            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                try:
                    await task
                except Exception:
                    pass

                raise

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("MemoryStore is not initialized")

    async def initialize(self) -> None:
        if self._initialized:
            return

        await self._run_write(
            initialize_database,
            self._path,
        )

        self._initialized = True

    async def commit(
        self,
        items: list[MemoryItem],
        *,
        context_id: str,
        processor: str,
        idempotency_key: str,
        checkpoint: MemoryCheckpointAdvance | None = None,
    ) -> MemoryCommitResult:
        self._require_initialized()

        context_id = context_id.strip()
        processor = processor.strip()
        idempotency_key = idempotency_key.strip()

        if not context_id or not processor or not idempotency_key:
            raise ValueError("context_id, processor and idempotency_key cannot be empty")

        return await self._run_write(
            commit_sync,
            self._path,
            items,
            context_id,
            processor,
            idempotency_key,
            checkpoint,
        )

    async def get_many(
        self,
        memory_ids: list[str],
    ) -> list[MemoryItem]:
        self._require_initialized()

        return await self._run_read(
            get_many_sync,
            self._path,
            memory_ids,
        )

    async def get_visible(
        self,
        memory_ids: list[str],
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
    ) -> list[MemoryItem]:
        self._require_initialized()

        return await self._run_read(
            get_visible_sync,
            self._path,
            memory_ids,
            owner_refs,
            context,
        )

    async def resolve_current(
        self,
        memory_ids: list[str],
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
    ) -> list[MemoryItem]:
        self._require_initialized()

        return await self._run_read(
            resolve_current_sync,
            self._path,
            memory_ids,
            owner_refs,
            context,
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
        self._require_initialized()

        return await self._run_read(
            query_visible_sync,
            self._path,
            owner_refs,
            context,
            memory_type,
            kind,
            limit,
        )

    async def get_checkpoint(
        self,
        *,
        context_id: str,
        processor: str,
    ) -> int:
        self._require_initialized()

        context_id = context_id.strip()
        processor = processor.strip()

        if not context_id or not processor:
            raise ValueError("context_id and processor cannot be empty")

        return await self._run_read(
            get_checkpoint_sync,
            self._path,
            context_id,
            processor,
        )

    async def claim_outbox(
        self,
        *,
        target: MemoryOutboxTarget,
        worker_id: str,
        limit: int = 64,
        lease_seconds: float = 30.0,
    ) -> list[MemoryOutboxEvent]:
        self._require_initialized()

        worker_id = worker_id.strip()

        if not worker_id:
            raise ValueError("worker_id cannot be empty")

        if limit <= 0:
            return []

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        return await self._run_write(
            claim_outbox_sync,
            self._path,
            target,
            worker_id,
            limit,
            lease_seconds,
        )

    async def complete_outbox(
        self,
        event_ids: list[int],
        *,
        worker_id: str,
    ) -> None:
        self._require_initialized()

        if not event_ids:
            return

        worker_id = worker_id.strip()

        if not worker_id:
            raise ValueError("worker_id cannot be empty")

        await self._run_write(
            complete_outbox_sync,
            self._path,
            event_ids,
            worker_id,
        )

    async def retry_outbox(
        self,
        event_id: int,
        *,
        worker_id: str,
        error: str,
        delay_seconds: float,
    ) -> None:
        self._require_initialized()

        worker_id = worker_id.strip()

        if not worker_id:
            raise ValueError("worker_id cannot be empty")

        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")

        await self._run_write(
            retry_outbox_sync,
            self._path,
            int(event_id),
            worker_id,
            error,
            delay_seconds,
        )
