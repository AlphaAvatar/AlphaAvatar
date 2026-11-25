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
import math
from collections import deque
from dataclasses import dataclass
from threading import RLock

from .enums import SessionEventKind
from .schemas import SessionEvent, SessionStreamRead, validate_identity


@dataclass(slots=True)
class _Consumer:
    cursor: int = 0


class SessionStream:
    """Bounded session events, published only by their owning SessionRuntime.

    Reading does not acknowledge events. A consumer commits only after its own work succeeds.
    A reported gap requires explicit recovery: a snapshot repairs current state, but does not
    replay storage effects. Closing leaves retained events available until consumers drain them.
    """

    def __init__(self, *, session_id: str, maxlen: int = 256, _lock: RLock | None = None) -> None:
        validate_identity(session_id, name="session_id")
        if not isinstance(maxlen, int) or isinstance(maxlen, bool) or maxlen <= 0:
            raise ValueError("maxlen must be a positive integer")
        self.session_id = session_id
        self.maxlen = maxlen
        self._events: deque[SessionEvent] = deque(maxlen=maxlen)
        self._consumers: dict[str, _Consumer] = {}
        self._publish_waiters: set[asyncio.Future[None]] = set()
        self._commit_waiters: set[asyncio.Future[None]] = set()
        self._sequence = 0
        self._closed = False
        self._lock = _lock if _lock is not None else RLock()

    @property
    def latest_sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def _consumer(self, consumer_id: str) -> _Consumer:
        validate_identity(consumer_id, name="consumer_id")
        return self._consumers.setdefault(consumer_id, _Consumer())

    def consumer_cursor(self, consumer_id: str) -> int:
        validate_identity(consumer_id, name="consumer_id")
        with self._lock:
            state = self._consumers.get(consumer_id)
            return 0 if state is None else state.cursor

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

    def _append(self, event: SessionEvent) -> tuple[asyncio.Future[None], ...]:
        """Owner-only append; the shared lock also guards the SessionRuntime state update."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Session event stream is closed")
            if event.session_id != self.session_id or event.sequence != self._sequence + 1:
                raise ValueError("Session event must belong to this stream and be consecutive")
            self._events.append(event)
            self._sequence = event.sequence
            self._closed = event.kind is SessionEventKind.CLOSED
            waiters = tuple(self._publish_waiters)
            self._publish_waiters.clear()
            if self._closed:
                waiters += tuple(self._commit_waiters)
                self._commit_waiters.clear()
            return waiters

    @staticmethod
    def _validate_timeout(timeout: float | None) -> None:
        if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be finite and nonnegative")

    async def wait_for_pending(self, *, consumer_id: str, timeout: float | None = None) -> bool:
        self._validate_timeout(timeout)
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        with self._lock:
            state = self._consumer(consumer_id)
        while True:
            with self._lock:
                if self._consumers.get(consumer_id) is not state:
                    return False
                if self._sequence > state.cursor:
                    return True
                if self._closed:
                    return False
                waiter = loop.create_future()
                self._publish_waiters.add(waiter)
            try:
                remaining = None if deadline is None else deadline - loop.time()
                if remaining is not None and remaining <= 0:
                    return False
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

    def read_pending(self, *, consumer_id: str, limit: int | None = None) -> SessionStreamRead:
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0
        ):
            raise ValueError("limit must be a positive integer")
        with self._lock:
            committed = self._consumer(consumer_id).cursor
            events = tuple(self._events)
            latest, closed = self._sequence, self._closed
        first = events[0].sequence if events else None
        missed = max(0, first - committed - 1) if first is not None else 0
        cursor = max(committed, first - 1 if first is not None else committed)
        items = tuple(event for event in events if event.sequence > committed)
        if limit is not None:
            items = items[:limit]
        if items:
            cursor = items[-1].sequence
        return SessionStreamRead(items, cursor, committed, first, latest, missed, closed)

    def commit(self, *, consumer_id: str, cursor_seq: int) -> None:
        if not isinstance(cursor_seq, int) or isinstance(cursor_seq, bool) or cursor_seq < 0:
            raise ValueError("cursor_seq must be a nonnegative integer")
        with self._lock:
            if cursor_seq > self._sequence:
                raise ValueError("Cannot commit a future session sequence")
            state = self._consumer(consumer_id)
            if cursor_seq <= state.cursor:
                return
            state.cursor = cursor_seq
            waiters = tuple(self._commit_waiters)
            self._commit_waiters.clear()
        self._wake(waiters)

    async def wait_until_consumed(
        self, *, consumer_id: str, cursor_seq: int, timeout: float | None = None
    ) -> bool:
        if not isinstance(cursor_seq, int) or isinstance(cursor_seq, bool) or cursor_seq <= 0:
            raise ValueError("cursor_seq must be a positive integer")
        self._validate_timeout(timeout)
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        with self._lock:
            if cursor_seq > self._sequence:
                raise ValueError("Cannot wait for a future session sequence")
            state = self._consumer(consumer_id)
        while True:
            with self._lock:
                if self._consumers.get(consumer_id) is not state:
                    return False
                if state.cursor >= cursor_seq:
                    return True
                waiter = loop.create_future()
                self._commit_waiters.add(waiter)
            try:
                remaining = None if deadline is None else deadline - loop.time()
                if remaining is not None and remaining <= 0:
                    return False
                if remaining is None:
                    await waiter
                else:
                    try:
                        await asyncio.wait_for(waiter, remaining)
                    except TimeoutError:
                        return False
            finally:
                with self._lock:
                    self._commit_waiters.discard(waiter)

    def clear_consumer(self, consumer_id: str) -> None:
        validate_identity(consumer_id, name="consumer_id")
        with self._lock:
            self._consumers.pop(consumer_id, None)
            waiters = tuple(self._publish_waiters | self._commit_waiters)
            self._publish_waiters.clear()
            self._commit_waiters.clear()
        self._wake(waiters)
