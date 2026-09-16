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
from abc import ABC, abstractmethod

from .enums import MemoryKind, MemoryOutboxTarget, MemoryType
from .schemas import (
    MemoryCheckpointAdvance,
    MemoryCommitResult,
    MemoryContextRef,
    MemoryItem,
    MemoryOutboxEvent,
    MemoryOwnerRef,
)


class MemoryStoreConflict(RuntimeError):
    pass


class MemoryRevisionConflict(MemoryStoreConflict):
    pass


class MemoryCheckpointConflict(MemoryStoreConflict):
    pass


class MemoryStoreBackend(ABC):
    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def commit(
        self,
        items: list[MemoryItem],
        *,
        context_id: str,
        processor: str,
        idempotency_key: str,
        checkpoint: MemoryCheckpointAdvance | None = None,
    ) -> MemoryCommitResult: ...

    @abstractmethod
    async def get_many(self, memory_ids: list[str]) -> list[MemoryItem]: ...

    @abstractmethod
    async def get_visible(
        self,
        memory_ids: list[str],
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
    ) -> list[MemoryItem]: ...

    @abstractmethod
    async def resolve_current(
        self,
        memory_ids: list[str],
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
    ) -> list[MemoryItem]: ...

    @abstractmethod
    async def query_visible(
        self,
        *,
        owner_refs: list[MemoryOwnerRef],
        context: MemoryContextRef,
        memory_type: MemoryType | None = None,
        kind: MemoryKind | None = None,
        limit: int = 100,
    ) -> list[MemoryItem]: ...

    @abstractmethod
    async def get_checkpoint(self, *, context_id: str, processor: str) -> int: ...

    @abstractmethod
    async def claim_outbox(
        self,
        *,
        target: MemoryOutboxTarget,
        worker_id: str,
        limit: int = 64,
        lease_seconds: float = 30.0,
    ) -> list[MemoryOutboxEvent]: ...

    @abstractmethod
    async def complete_outbox(
        self,
        event_ids: list[int],
        *,
        worker_id: str,
    ) -> None: ...

    @abstractmethod
    async def retry_outbox(
        self,
        event_id: int,
        *,
        worker_id: str,
        error: str,
        delay_seconds: float,
    ) -> None: ...
