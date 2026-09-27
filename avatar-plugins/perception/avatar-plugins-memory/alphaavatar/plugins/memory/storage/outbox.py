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
from collections.abc import Awaitable, Callable
from uuid import uuid4

from alphaavatar.agents.memory import MemoryStoreBackend
from alphaavatar.agents.memory.enums import MemoryOutboxTarget
from alphaavatar.agents.memory.schemas import MemoryItem, MemoryOutboxEvent

from ..log import logger

OutboxHandler = Callable[[list[MemoryItem]], Awaitable[None]]


class MemoryOutboxWorker:
    def __init__(
        self,
        *,
        backend: MemoryStoreBackend,
        target: MemoryOutboxTarget,
        handler: OutboxHandler,
        batch_size: int = 64,
        lease_seconds: float = 60.0,
        poll_interval: float = 1.0,
        retry_base: float = 0.5,
        retry_max: float = 30.0,
    ) -> None:
        self._backend = backend
        self._target = target
        self._handler = handler
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._poll_interval = poll_interval
        self._retry_base = retry_base
        self._retry_max = retry_max
        self._worker_id = f"memory:{target.value}:{uuid4().hex}"
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name=f"memory_outbox:{self._target.value}")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping = True
        self._wake.set()
        try:
            await self._task
        finally:
            self._task = None

    def wake(self) -> None:
        if not self._stopping:
            self._wake.set()

    @staticmethod
    def _expected_revisions(events: list[MemoryOutboxEvent]) -> dict[str, int]:
        revisions: dict[str, int] = {}
        for event in events:
            revisions[event.memory_id] = max(event.revision, revisions.get(event.memory_id, 0))
        return revisions

    async def _hydrate(self, events: list[MemoryOutboxEvent]) -> list[MemoryItem]:
        revisions = self._expected_revisions(events)
        memory_ids = list(revisions)
        items = await self._backend.get_many(memory_ids)
        by_id = {item.memory_id: item for item in items}

        missing = [memory_id for memory_id in memory_ids if memory_id not in by_id]
        if missing:
            raise RuntimeError(f"Outbox references missing memories: {missing}")

        stale = [
            memory_id
            for memory_id, revision in revisions.items()
            if by_id[memory_id].revision < revision
        ]
        if stale:
            raise RuntimeError(f"Outbox revision exceeds authoritative memory revision: {stale}")

        return [by_id[memory_id] for memory_id in memory_ids]

    def _retry_delay(self, attempts: int) -> float:
        return min(self._retry_base * 2 ** max(attempts - 1, 0), self._retry_max)

    async def _retry(self, events: list[MemoryOutboxEvent], error: BaseException) -> None:
        message = f"{type(error).__name__}: {error}"

        for event in events:
            try:
                await self._backend.retry_outbox(
                    event.event_id,
                    worker_id=self._worker_id,
                    error=message,
                    delay_seconds=self._retry_delay(event.attempts),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Memory outbox retry failed target=%s event=%s",
                    self._target.value,
                    event.event_id,
                )

    async def _process_once(self) -> bool:
        events = await self._backend.claim_outbox(
            target=self._target,
            worker_id=self._worker_id,
            limit=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        if not events:
            return False

        try:
            items = await self._hydrate(events)
            await self._handler(items)
            await self._backend.complete_outbox(
                [event.event_id for event in events],
                worker_id=self._worker_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Memory outbox processing failed target=%s events=%d",
                self._target.value,
                len(events),
            )
            await self._retry(events, exc)

        return True

    async def _run(self) -> None:
        while not self._stopping:
            try:
                if await self._process_once():
                    continue

                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Memory outbox worker failed target=%s", self._target.value)
                await asyncio.sleep(self._poll_interval)
