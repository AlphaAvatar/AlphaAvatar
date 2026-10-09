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
from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import uuid4

from alphaavatar.core.time import RuntimeClock

from .schemas import OutputJournalEvent, OutputScope

T = TypeVar("T")


class OutputJournalFull(RuntimeError):
    """Publication was rejected; no record, cursor or eviction was committed."""


class OutputJournalGap(RuntimeError):
    pass


class OutputConsumerFailed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OutputJournalRead(Generic[T]):
    items: tuple[OutputJournalEvent[T], ...]
    cursor_seq: int
    committed_cursor_seq: int
    latest_seq: int
    missed_count: int = 0

    @property
    def has_gap(self) -> bool:
        return self.missed_count > 0


@dataclass(slots=True)
class _Consumer:
    cursor: int
    read_cursor: int
    required: bool
    error: Exception | None = None


class OutputJournal(Generic[T]):
    """Single-event-loop journal; synchronous admission never executes consumer code.

    Lossless journals evict only records acknowledged by every required consumer.
    With no required consumer, records are retained until capacity rejection.
    Lossy diagnostic journals report gaps. Sequences are local to this journal,
    not OutputRuntime's media timeline. Replay detection is retention-window scoped.
    """

    def __init__(
        self,
        *,
        session_id: str,
        clock: RuntimeClock,
        max_items: int,
        max_bytes: int,
        lossless: bool,
    ) -> None:
        if not session_id or type(max_items) is not int or max_items < 1:
            raise ValueError("Journal requires session_id and positive max_items")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("Journal requires positive max_bytes")

        self._session_id, self._clock = session_id, clock
        self._max_items, self._max_bytes, self._lossless = max_items, max_bytes, lossless
        self._events: deque[OutputJournalEvent[T]] = deque()
        self._keys: dict[str, OutputJournalEvent[T]] = {}
        self._consumers: dict[str, _Consumer] = {}
        self._waiters: set[asyncio.Future[None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sequence = self._bytes = 0
        self._closed = False

    def _owner(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("Output journals have one event-loop owner")

    def _wake(self) -> None:
        waiters, self._waiters = self._waiters, set()
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    @property
    def latest_sequence(self) -> int:
        return self._sequence

    @property
    def retained_count(self) -> int:
        return len(self._events)

    @property
    def retained_bytes(self) -> int:
        return self._bytes

    def register(self, consumer_id: str, *, required: bool = False, after: int = 0) -> None:
        self._owner()
        if self._closed:
            raise RuntimeError("Output journal is closed")
        if not isinstance(consumer_id, str) or not consumer_id:
            raise ValueError("Consumer identity is required")
        if consumer_id in self._consumers:
            raise ValueError(f"Output consumer already registered: {consumer_id}")
        if type(after) is not int or not 0 <= after <= self._sequence:
            raise ValueError("Invalid initial consumer cursor")
        first = self._events[0].sequence if self._events else self._sequence + 1
        if required and after < first - 1:
            raise OutputJournalGap("Required consumer cannot begin after records were evicted")
        self._consumers[consumer_id] = _Consumer(after, after, required)

    def _consumer(self, consumer_id: str) -> _Consumer:
        try:
            consumer = self._consumers[consumer_id]
        except KeyError:
            raise ValueError(f"Unknown output consumer: {consumer_id}") from None
        if consumer.error is not None:
            raise OutputConsumerFailed(f"Output consumer failed: {consumer_id}") from consumer.error
        return consumer

    def unregister(self, consumer_id: str) -> None:
        self._owner()
        self._consumers.pop(consumer_id, None)
        self._wake()

    def fail(self, consumer_id: str, error: Exception) -> None:
        self._owner()
        if not isinstance(error, Exception):
            raise TypeError("Consumer failures must be Exceptions")
        consumer = self._consumers[consumer_id]
        if consumer.error is None:
            consumer.error = error
        self._wake()

    def append(
        self,
        *,
        key: str,
        scope: OutputScope,
        payload: T,
        digest: str,
        size_bytes: int,
    ) -> OutputJournalEvent[T]:
        self._owner()
        if self._closed:
            raise RuntimeError("Output journal is closed")
        if not isinstance(key, str) or not key or not isinstance(scope, OutputScope):
            raise ValueError("Journal entries require a key and scope")
        if type(size_bytes) is not int or not 0 < size_bytes <= self._max_bytes:
            raise OutputJournalFull("Record exceeds journal byte capacity")
        previous = self._keys.get(key)
        if previous is not None:
            if previous.scope != scope or previous.digest != digest:
                raise ValueError("Conflicting output batch replay")
            return previous

        required = [c for c in self._consumers.values() if c.required]
        if self._lossless and any(c.error is not None for c in required):
            raise OutputConsumerFailed("A required record consumer has failed")
        floor = min((c.cursor for c in required), default=0)
        count, size, remove = len(self._events), self._bytes, 0
        for event in self._events:
            if count < self._max_items and size + size_bytes <= self._max_bytes:
                break
            if self._lossless and event.sequence > floor:
                raise OutputJournalFull("Unacknowledged output records filled the journal")
            count -= 1
            size -= event.size_bytes
            remove += 1
        if count >= self._max_items or size + size_bytes > self._max_bytes:
            raise OutputJournalFull("Output journal is full")

        # Validate capacity before eviction. Admission has no suspension/cancellation point.
        now = self._clock.now()
        event = OutputJournalEvent(
            uuid4().hex,
            self._sequence + 1,
            self._session_id,
            now.unix_seconds,
            now.monotonic_ns,
            key,
            scope,
            payload,
            digest,
            size_bytes,
        )
        for _ in range(remove):
            removed = self._events.popleft()
            del self._keys[removed.key]
        self._events.append(event)
        self._keys[key] = event
        self._sequence, self._bytes = event.sequence, size + size_bytes
        self._wake()
        return event

    def read_pending(self, *, consumer_id: str, limit: int = 32) -> OutputJournalRead[T]:
        self._owner()
        if type(limit) is not int or limit < 1:
            raise ValueError("Read limit must be positive")
        consumer = self._consumer(consumer_id)
        first = self._events[0].sequence if self._events else self._sequence + 1
        missed = max(0, first - consumer.cursor - 1)
        if missed and consumer.required:
            raise OutputJournalGap("Required consumer missed records")
        items = tuple(e for e in self._events if e.sequence > consumer.cursor)[:limit]
        cursor = items[-1].sequence if items else max(consumer.cursor, first - 1)
        consumer.read_cursor = max(consumer.read_cursor, cursor)
        return OutputJournalRead(items, cursor, consumer.cursor, self._sequence, missed)

    def commit(self, *, consumer_id: str, cursor_seq: int) -> None:
        self._owner()
        consumer = self._consumer(consumer_id)
        if type(cursor_seq) is not int or not consumer.cursor <= cursor_seq <= consumer.read_cursor:
            raise ValueError("Cannot acknowledge unread output records")
        consumer.cursor = cursor_seq
        self._wake()

    async def wait_for_pending(self, *, consumer_id: str) -> bool:
        self._owner()
        while True:
            consumer = self._consumer(consumer_id)
            if consumer.cursor < self._sequence:
                return True
            if self._closed:
                return False
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.add(waiter)
            try:
                await waiter
            finally:
                self._waiters.discard(waiter)

    async def wait_until_consumed(self, *, consumer_id: str, cursor_seq: int) -> None:
        self._owner()
        if type(cursor_seq) is not int or not 0 <= cursor_seq <= self._sequence:
            raise ValueError("Cannot wait for a future output sequence")
        while self._consumer(consumer_id).cursor < cursor_seq:
            if self._closed:
                raise RuntimeError("Journal closed before consumer acknowledgement")
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.add(waiter)
            try:
                await waiter
            finally:
                self._waiters.discard(waiter)

    def close(self) -> None:
        self._owner()
        self._closed = True
        self._wake()
