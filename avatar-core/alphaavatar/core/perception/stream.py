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


@dataclass(slots=True, frozen=True)
class StreamRecord(Generic[T]):
    seq: int
    item: T
    published_monotonic: float


@dataclass(slots=True, frozen=True)
class StreamRead(Generic[T]):
    """
    Immutable snapshot returned by PerceptionStream.read_pending().

    cursor_seq:
        Highest sequence inspected by this read. This includes records skipped
        by predicate and an acknowledged retention gap boundary.

    committed_cursor_seq:
        Consumer cursor before this read. The cursor is not advanced until the
        caller explicitly invokes PerceptionStream.commit().

    latest_seq:
        Latest published sequence at the time the stream snapshot was taken.
    """

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
        """Number of records remaining after this read cursor."""
        return max(0, self.latest_seq - self.cursor_seq)

    @property
    def consumer_lag(self) -> int:
        """
        Backwards-compatible alias for records remaining after this read.

        Use committed_lag when measuring the consumer's currently committed
        position before commit().
        """
        return self.remaining_count

    @property
    def committed_lag(self) -> int:
        """Distance between the committed cursor and the latest sequence."""
        return max(0, self.latest_seq - self.committed_cursor_seq)


class PerceptionStream(Generic[T]):
    """
    Typed multi-consumer bounded stream.

    Each consumer owns an independent committed cursor.

    Publishing is synchronous and non-blocking with respect to consumers:
    records are appended under a short lock and asynchronous waiters are
    notified outside the lock.

    Slow consumers may lose records after retention eviction. Such loss is
    explicitly exposed through StreamRead.has_gap and missed_count.
    """

    def __init__(self, *, name: str, maxlen: int) -> None:
        if not name:
            raise ValueError("PerceptionStream name cannot be empty")
        if maxlen <= 0:
            raise ValueError(f"PerceptionStream maxlen must be positive: {maxlen}")

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

    @property
    def retained_count(self) -> int:
        with self._lock:
            return len(self._records)

    @staticmethod
    def _validate_consumer_id(consumer_id: str) -> None:
        if not consumer_id:
            raise ValueError("consumer_id cannot be empty")

    @staticmethod
    def _resolve_waiter(waiter: asyncio.Future[None]) -> None:
        if not waiter.done():
            waiter.set_result(None)

    def _first_unread_record_locked(self, cursor_seq: int) -> StreamRecord[T] | None:
        for record in self._records:
            if record.seq > cursor_seq:
                return record
        return None

    def _detach_waiters_locked(self) -> tuple[asyncio.Future[None], ...]:
        waiters = tuple(self._waiters)
        self._waiters.clear()
        return waiters

    def _wake_waiters(self, waiters: tuple[asyncio.Future[None], ...]) -> None:
        for waiter in waiters:
            if waiter.done():
                continue

            try:
                waiter.get_loop().call_soon_threadsafe(self._resolve_waiter, waiter)
            except RuntimeError:
                # The waiter event loop may already be closed during shutdown.
                continue

    def publish(self, item: T) -> int:
        """
        Publish one item and return its monotonically increasing sequence.

        Consumers are notified after releasing the stream lock. Publishing
        never waits for a consumer to process or commit the item.
        """

        with self._lock:
            self._seq += 1
            seq = self._seq
            self._records.append(
                StreamRecord(seq=seq, item=item, published_monotonic=time.monotonic())
            )
            waiters = self._detach_waiters_locked()

        self._wake_waiters(waiters)
        return seq

    async def wait_for_pending(
        self,
        *,
        consumer_id: str,
        timeout: float | None = None,
        min_age_sec: float = 0.0,
    ) -> bool:
        """
        Wait until an unread record is eligible for this consumer.

        min_age_sec applies to the oldest unread record. Unlike repeatedly
        calling read_pending(), this method waits for a young record to mature
        and therefore does not create a busy loop.

        Returns:
            True when an eligible unread record exists.
            False when timeout expires.

        Cancellation propagates normally for immediate runtime shutdown.
        """

        self._validate_consumer_id(consumer_id)

        if timeout is not None and timeout < 0:
            raise ValueError(f"timeout cannot be negative: {timeout}")
        if min_age_sec < 0:
            raise ValueError(f"min_age_sec cannot be negative: {min_age_sec}")

        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            waiter: asyncio.Future[None] | None = None
            maturation_delay: float | None = None
            now = time.monotonic()

            with self._lock:
                cursor = self._consumer_cursors.get(consumer_id, 0)
                first_unread = self._first_unread_record_locked(cursor)

                if first_unread is not None:
                    remaining_age = min_age_sec - (now - first_unread.published_monotonic)
                    if remaining_age <= 0:
                        return True
                    maturation_delay = remaining_age
                else:
                    waiter = loop.create_future()
                    self._waiters.add(waiter)

            remaining_timeout = None if deadline is None else deadline - time.monotonic()

            if remaining_timeout is not None and remaining_timeout <= 0:
                if waiter is not None:
                    with self._lock:
                        self._waiters.discard(waiter)
                return False

            try:
                if waiter is not None:
                    if remaining_timeout is None:
                        await waiter
                    else:
                        try:
                            await asyncio.wait_for(waiter, timeout=remaining_timeout)
                        except asyncio.TimeoutError:
                            return False
                else:
                    delay = maturation_delay or 0.0
                    if remaining_timeout is not None:
                        delay = min(delay, remaining_timeout)
                    await asyncio.sleep(delay)
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
        """
        Read pending items without advancing the committed consumer cursor.

        The stream is snapshotted under the lock, while predicate evaluation
        occurs outside the lock. This prevents slow or reentrant predicates
        from blocking publishers and other consumers.

        cursor_seq advances across:
        - records accepted into items;
        - records rejected by predicate;
        - an acknowledged retention gap boundary.

        The caller should commit cursor_seq after successfully handling the
        returned items and gap information.
        """

        self._validate_consumer_id(consumer_id)

        if min_age_sec < 0:
            raise ValueError(f"min_age_sec cannot be negative: {min_age_sec}")
        if limit is not None and limit <= 0:
            raise ValueError(f"limit must be positive when provided: {limit}")

        now = time.monotonic()

        with self._lock:
            committed_cursor = self._consumer_cursors.get(consumer_id, 0)
            records = tuple(self._records)
            latest_seq = self._seq

        first_available_seq = records[0].seq if records else None
        missed_count = (
            max(0, first_available_seq - committed_cursor - 1)
            if first_available_seq is not None
            else 0
        )

        # If retained data starts after the consumer cursor, acknowledge the
        # evicted range even when the first retained item is still too young.
        gap_boundary = (
            first_available_seq - 1 if first_available_seq is not None else committed_cursor
        )
        cursor_seq = max(committed_cursor, gap_boundary)
        items: list[T] = []

        for record in records:
            if record.seq <= committed_cursor:
                continue

            # Records are ordered by publication time, so later records will
            # also be too young once this condition is reached.
            if now - record.published_monotonic < min_age_sec:
                break

            cursor_seq = record.seq

            if predicate is not None and not predicate(record.item):
                continue

            items.append(record.item)

            if limit is not None and len(items) >= limit:
                break

        return StreamRead(
            items=items,
            cursor_seq=cursor_seq,
            committed_cursor_seq=committed_cursor,
            first_available_seq=first_available_seq,
            latest_seq=latest_seq,
            missed_count=missed_count,
        )

    def commit(self, *, consumer_id: str, cursor_seq: int) -> None:
        """
        Commit a successfully processed read cursor.

        Cursor commits are monotonic. Committing an older cursor is a no-op;
        committing a sequence that has never been published is rejected.
        """

        self._validate_consumer_id(consumer_id)

        if cursor_seq < 0:
            raise ValueError(f"cursor_seq cannot be negative: {cursor_seq}")

        with self._lock:
            if cursor_seq > self._seq:
                raise ValueError(
                    f"Cannot commit future cursor on stream {self.name!r}: "
                    f"cursor_seq={cursor_seq}, latest_seq={self._seq}"
                )

            previous = self._consumer_cursors.get(consumer_id, 0)
            if cursor_seq > previous:
                self._consumer_cursors[consumer_id] = cursor_seq

    def clear_consumer(self, consumer_id: str) -> None:
        """Remove the committed cursor owned by one consumer."""
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
            cursor = self._consumer_cursors.get(consumer_id, 0)
            return max(0, self._seq - cursor)
