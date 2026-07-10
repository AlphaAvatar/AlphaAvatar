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
    items: list[T]
    cursor_seq: int


class PerceptionStream(Generic[T]):
    """
    Typed multi-consumer stream.

    Each consumer owns an independent cursor.
    """

    def __init__(
        self,
        *,
        name: str,
        maxlen: int,
    ) -> None:
        self.name = name

        self._records: deque[StreamRecord[T]] = deque(maxlen=maxlen)
        self._consumer_cursors: dict[str, int] = {}

        self._seq = 0
        self._lock = RLock()

    def publish(self, item: T) -> int:
        with self._lock:
            self._seq += 1

            self._records.append(
                StreamRecord(
                    seq=self._seq,
                    item=item,
                    published_monotonic=time.monotonic(),
                )
            )

            return self._seq

    def read_pending(
        self,
        *,
        consumer_id: str,
        predicate: Callable[[T], bool] | None = None,
        min_age_sec: float = 0.0,
        limit: int | None = None,
    ) -> StreamRead[T]:
        """
        Read pending items without committing.

        min_age_sec:
            Allows downstream consumers to wait briefly for asynchronous
            annotations before consuming a frame.
        """

        now = time.monotonic()

        with self._lock:
            cursor = self._consumer_cursors.get(consumer_id, 0)
            cursor_seq = cursor
            items: list[T] = []

            for record in self._records:
                if record.seq <= cursor:
                    continue

                age = now - record.published_monotonic

                # Records are ordered by publication time. Once one record is
                # too new, later records will also be too new.
                if age < min_age_sec:
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
            )

    def commit(
        self,
        *,
        consumer_id: str,
        cursor_seq: int,
    ) -> None:
        with self._lock:
            previous = self._consumer_cursors.get(consumer_id, 0)
            self._consumer_cursors[consumer_id] = max(
                previous,
                cursor_seq,
            )

    def clear_consumer(self, consumer_id: str) -> None:
        with self._lock:
            self._consumer_cursors.pop(consumer_id, None)
