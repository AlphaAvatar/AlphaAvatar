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
from threading import RLock
from uuid import uuid4

from .schema import TurnEvent, TurnSnapshot


@dataclass(frozen=True, slots=True)
class TurnStreamRead:
    items: tuple[TurnEvent, ...]
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


class TurnStream:
    def __init__(self, *, session_id: str, maxlen: int = 256) -> None:
        if not session_id:
            raise ValueError("session_id cannot be empty")
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")

        self.session_id = session_id
        self.maxlen = maxlen
        self._events: deque[TurnEvent] = deque(maxlen=maxlen)
        self._consumer_cursors: dict[str, int] = {}
        self._publish_waiters: set[asyncio.Future[None]] = set()
        self._commit_waiters: set[asyncio.Future[None]] = set()
        self._sequence = 0
        self._lock = RLock()

    @property
    def latest_sequence(self) -> int:
        with self._lock:
            return self._sequence

    @staticmethod
    def _validate_consumer_id(consumer_id: str) -> None:
        if not consumer_id:
            raise ValueError("consumer_id cannot be empty")

    @staticmethod
    def _resolve(waiter: asyncio.Future[None]) -> None:
        if not waiter.done():
            waiter.set_result(None)

    @classmethod
    def _wake(cls, waiters: tuple[asyncio.Future[None], ...]) -> None:
        for waiter in waiters:
            if waiter.done():
                continue
            try:
                waiter.get_loop().call_soon_threadsafe(cls._resolve, waiter)
            except RuntimeError:
                pass

    def publish(self, snapshot: TurnSnapshot) -> TurnEvent:
        with self._lock:
            self._sequence += 1
            event = TurnEvent(
                event_id=uuid4().hex,
                session_id=self.session_id,
                sequence=self._sequence,
                snapshot=snapshot,
            )
            self._events.append(event)
            waiters = tuple(self._publish_waiters)
            self._publish_waiters.clear()

        self._wake(waiters)
        return event

    async def wait_for_pending(
        self,
        *,
        consumer_id: str,
        timeout: float | None = None,
    ) -> bool:
        self._validate_consumer_id(consumer_id)
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")

        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout

        while True:
            with self._lock:
                cursor = self._consumer_cursors.get(consumer_id, 0)
                if self._events and self._events[-1].sequence > cursor:
                    return True
                waiter = loop.create_future()
                self._publish_waiters.add(waiter)

            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                with self._lock:
                    self._publish_waiters.discard(waiter)
                return False

            try:
                if remaining is None:
                    await waiter
                else:
                    try:
                        await asyncio.wait_for(waiter, remaining)
                    except TimeoutError:
                        return False
            finally:
                with self._lock:
                    self._publish_waiters.discard(waiter)

    def read_pending(
        self,
        *,
        consumer_id: str,
        limit: int | None = None,
    ) -> TurnStreamRead:
        self._validate_consumer_id(consumer_id)
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        with self._lock:
            committed = self._consumer_cursors.get(consumer_id, 0)
            events = tuple(self._events)
            latest = self._sequence

        first = events[0].sequence if events else None
        missed = max(0, first - committed - 1) if first is not None else 0
        cursor = max(committed, first - 1 if first is not None else committed)
        items = []

        for event in events:
            if event.sequence <= committed:
                continue
            cursor = event.sequence
            items.append(event)
            if limit is not None and len(items) >= limit:
                break

        return TurnStreamRead(tuple(items), cursor, committed, first, latest, missed)

    def commit(self, *, consumer_id: str, cursor_seq: int) -> None:
        self._validate_consumer_id(consumer_id)
        if cursor_seq < 0:
            raise ValueError("cursor_seq cannot be negative")

        with self._lock:
            if cursor_seq > self._sequence:
                raise ValueError("Cannot commit future turn sequence")
            if cursor_seq <= self._consumer_cursors.get(consumer_id, 0):
                return

            self._consumer_cursors[consumer_id] = cursor_seq
            waiters = tuple(self._commit_waiters)
            self._commit_waiters.clear()

        self._wake(waiters)

    async def wait_until_consumed(self, *, consumer_id: str, cursor_seq: int) -> None:
        self._validate_consumer_id(consumer_id)
        if cursor_seq <= 0:
            raise ValueError("cursor_seq must be positive")

        loop = asyncio.get_running_loop()

        while True:
            with self._lock:
                if self._consumer_cursors.get(consumer_id, 0) >= cursor_seq:
                    return
                waiter = loop.create_future()
                self._commit_waiters.add(waiter)

            try:
                await waiter
            finally:
                with self._lock:
                    self._commit_waiters.discard(waiter)

    def clear_consumer(self, consumer_id: str) -> None:
        self._validate_consumer_id(consumer_id)
        with self._lock:
            self._consumer_cursors.pop(consumer_id, None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            for consumer_id in self._consumer_cursors:
                self._consumer_cursors[consumer_id] = self._sequence
