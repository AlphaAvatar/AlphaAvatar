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
from math import isfinite

from ..enums import OutputPlaybackType


@dataclass(frozen=True, slots=True)
class OutputPlayback:
    """Local transport measurements, not proof of remote listening."""

    type: OutputPlaybackType
    played_duration_sec: float
    pushed_duration_sec: float
    queued_duration_sec: float

    def __post_init__(self) -> None:
        if type(self.type) is not OutputPlaybackType:
            raise TypeError("Expected OutputPlaybackType")
        values = (self.played_duration_sec, self.pushed_duration_sec, self.queued_duration_sec)
        if any(
            type(value) not in (int, float) or not isfinite(value) or value < 0 for value in values
        ):
            raise ValueError("Playback durations must be finite and nonnegative")
        if self.played_duration_sec > self.pushed_duration_sec:
            raise ValueError("Confirmed played duration cannot exceed confirmed pushed duration")
        # Queued duration may include an interrupted, unconfirmed in-flight capture.
