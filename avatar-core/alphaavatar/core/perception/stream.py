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
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class StreamRecord(Generic[T]):
    seq: int
    item: T
    published_monotonic: float


@dataclass(frozen=True, slots=True)
class StreamRead(Generic[T]):
    items: list[T]
    cursor_seq: int
    committed_cursor_seq: int
    first_available_seq: int | None
    latest_seq: int
    missed_count: int = 0

    @property
    def has_gap(self) -> bool:
        return self.missed_count > 0

    @property
    def remaining_count(self) -> int:
        return max(0, self.latest_seq - self.cursor_seq)

    @property
    def committed_lag(self) -> int:
        return max(0, self.latest_seq - self.committed_cursor_seq)


@dataclass(frozen=True, slots=True)
class StreamSlice(Generic[T]):
    items: tuple[T, ...]
    after_seq: int
    until_seq: int
    first_available_seq: int | None
    latest_seq: int
    missed_count: int = 0

    @property
    def has_gap(self) -> bool:
        return self.missed_count > 0


class PerceptionStream(Generic[T]):
    def __init__(self, *, name: str, maxlen: int) -> None:
        if not name:
            raise ValueError("PerceptionStream name cannot be empty")
        if maxlen <= 0:
            raise ValueError("PerceptionStream maxlen must be positive")

        self.name = name
        self.maxlen = maxlen

        self._records: deque[StreamRecord[T]] = deque(maxlen=maxlen)
        self._consumer_cursors: dict[str, int] = {}
        self._waiters: set[asyncio.Future[None]] = set()

        self._seq = 0
        self._lock = RLock()

    @property
    def latest_seq(self) -> int:
        with self._lock:
            return self._seq

    @property
    def first_available_seq(self) -> int | None:
        with self._lock:
            return self._records[0].seq if self._records else None

    @staticmethod
    def _validate_consumer_id(consumer_id: str) -> None:
        if not consumer_id:
            raise ValueError("consumer_id cannot be empty")

    @staticmethod
    def _resolve_waiter(waiter: asyncio.Future[None]) -> None:
        if not waiter.done():
            waiter.set_result(None)

    def _first_unread_locked(self, cursor: int) -> StreamRecord[T] | None:
        return next((record for record in self._records if record.seq > cursor), None)

    def publish(self, item: T) -> int:
        with self._lock:
            self._seq += 1
            sequence = self._seq
            self._records.append(StreamRecord(sequence, item, time.monotonic()))
            waiters = tuple(self._waiters)
            self._waiters.clear()

        for waiter in waiters:
            if waiter.done():
                continue

            try:
                waiter.get_loop().call_soon_threadsafe(self._resolve_waiter, waiter)
            except RuntimeError:
                pass
        return sequence

    async def wait_for_pending(
        self,
        *,
        consumer_id: str,
        timeout: float | None = None,
        min_age_sec: float = 0.0,
    ) -> bool:
        self._validate_consumer_id(consumer_id)
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        if min_age_sec < 0:
            raise ValueError("min_age_sec cannot be negative")

        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while True:
            waiter: asyncio.Future[None] | None = None
            now = time.monotonic()
            with self._lock:
                cursor = self._consumer_cursors.get(consumer_id, 0)
                record = self._first_unread_locked(cursor)
                if record is not None:
                    maturation = min_age_sec - (now - record.published_monotonic)
                    if maturation <= 0:
                        return True
                else:
                    maturation = None
                    waiter = loop.create_future()
                    self._waiters.add(waiter)

            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                if waiter is not None:
                    with self._lock:
                        self._waiters.discard(waiter)
                return False
            try:
                if waiter is not None:
                    if remaining is None:
                        await waiter
                    else:
                        try:
                            await asyncio.wait_for(waiter, remaining)
                        except TimeoutError:
                            return False
                else:
                    delay = maturation or 0.0
                    await asyncio.sleep(delay if remaining is None else min(delay, remaining))
            finally:
                if waiter is not None:
                    with self._lock:
                        self._waiters.discard(waiter)

    def read_pending(
        self,
        *,
        consumer_id: str,
        predicate: Callable[[T], bool] | None = None,
        min_age_sec: float = 0.0,
        limit: int | None = None,
    ) -> StreamRead[T]:
        self._validate_consumer_id(consumer_id)
        if min_age_sec < 0:
            raise ValueError("min_age_sec cannot be negative")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        now = time.monotonic()
        with self._lock:
            committed = self._consumer_cursors.get(consumer_id, 0)
            records = tuple(self._records)
            latest = self._seq

        first = records[0].seq if records else None
        missed = max(0, first - committed - 1) if first is not None else 0
        cursor = max(committed, first - 1 if first is not None else committed)
        items: list[T] = []
        for record in records:
            if record.seq <= committed:
                continue
            if now - record.published_monotonic < min_age_sec:
                break
            cursor = record.seq
            if predicate is None or predicate(record.item):
                items.append(record.item)
                if limit is not None and len(items) >= limit:
                    break

        return StreamRead(items, cursor, committed, first, latest, missed)

    def read_range(self, *, after_seq: int, until_seq: int | None = None) -> StreamSlice[T]:
        if after_seq < 0:
            raise ValueError("after_seq cannot be negative")

        with self._lock:
            records = tuple(self._records)
            latest = self._seq

        resolved_until = latest if until_seq is None else until_seq
        if resolved_until < after_seq:
            raise ValueError("until_seq cannot precede after_seq")
        if resolved_until > latest:
            raise ValueError(f"Cannot read future sequence from stream {self.name!r}")

        first = records[0].seq if records else None
        if first is None:
            missed = max(0, resolved_until - after_seq)
        else:
            missed = max(0, min(resolved_until, first - 1) - after_seq)

        items = tuple(record.item for record in records if after_seq < record.seq <= resolved_until)
        return StreamSlice(items, after_seq, resolved_until, first, latest, missed)

    def commit(self, *, consumer_id: str, cursor_seq: int) -> None:
        self._validate_consumer_id(consumer_id)

        if cursor_seq < 0:
            raise ValueError("cursor_seq cannot be negative")

        with self._lock:
            if cursor_seq > self._seq:
                raise ValueError(f"Cannot commit future cursor on stream {self.name!r}")

            if cursor_seq > self._consumer_cursors.get(consumer_id, 0):
                self._consumer_cursors[consumer_id] = cursor_seq

    def clear_consumer(self, consumer_id: str) -> None:
        self._validate_consumer_id(consumer_id)

        with self._lock:
            self._consumer_cursors.pop(consumer_id, None)

    def get_consumer_cursor(self, consumer_id: str) -> int:
        self._validate_consumer_id(consumer_id)

        with self._lock:
            return self._consumer_cursors.get(consumer_id, 0)

    def get_consumer_lag(self, consumer_id: str) -> int:
        """Return the consumer's committed sequence lag."""
        self._validate_consumer_id(consumer_id)

        with self._lock:
            return max(0, self._seq - self._consumer_cursors.get(consumer_id, 0))
