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

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True, slots=True)
class PerceptionRetentionPolicy:
    retention_sec: float = 60.0
    headroom: float = 1.25

    def __post_init__(self) -> None:
        if self.retention_sec <= 0:
            raise ValueError("retention_sec must be positive")
        if self.headroom < 1:
            raise ValueError("headroom must be at least 1")

    def capacity(self, interval_sec: float) -> int:
        if interval_sec <= 0:
            raise ValueError("interval_sec must be positive")
        return max(1, ceil(self.retention_sec / interval_sec * self.headroom))
