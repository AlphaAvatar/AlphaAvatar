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
from dataclasses import dataclass

_NS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True, slots=True)
class RuntimeTime:
    unix_ns: int
    monotonic_ns: int

    @property
    def unix_seconds(self) -> float:
        return self.unix_ns / _NS_PER_SECOND

    @property
    def monotonic_seconds(self) -> float:
        return self.monotonic_ns / _NS_PER_SECOND

    def elapsed_since(self, other: RuntimeTime) -> float:
        return max(0, self.monotonic_ns - other.monotonic_ns) / _NS_PER_SECOND

    def shifted(self, seconds: float) -> RuntimeTime:
        delta_ns = round(seconds * _NS_PER_SECOND)
        return RuntimeTime(
            unix_ns=self.unix_ns + delta_ns,
            monotonic_ns=self.monotonic_ns + delta_ns,
        )


@dataclass(frozen=True, slots=True)
class RuntimeTimeRange:
    start: RuntimeTime
    end: RuntimeTime

    def __post_init__(self) -> None:
        if self.end.monotonic_ns < self.start.monotonic_ns:
            raise ValueError("RuntimeTimeRange end cannot precede start")

    @classmethod
    def point(cls, at: RuntimeTime) -> RuntimeTimeRange:
        return cls(start=at, end=at)

    @property
    def duration_sec(self) -> float:
        return self.end.elapsed_since(self.start)

    @property
    def midpoint_monotonic_ns(self) -> int:
        return (self.start.monotonic_ns + self.end.monotonic_ns) // 2

    def overlaps(self, other: RuntimeTimeRange) -> bool:
        return (
            self.start.monotonic_ns <= other.end.monotonic_ns
            and other.start.monotonic_ns <= self.end.monotonic_ns
        )

    def contains_monotonic_ns(self, value: int) -> bool:
        return self.start.monotonic_ns <= value <= self.end.monotonic_ns


class RuntimeClock:
    __slots__ = ()

    def now(self) -> RuntimeTime:
        return RuntimeTime(unix_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())

    def point(self) -> RuntimeTimeRange:
        return RuntimeTimeRange.point(self.now())
