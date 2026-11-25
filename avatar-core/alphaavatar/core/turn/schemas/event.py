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

from .snapshot import TurnSnapshot


@dataclass(frozen=True, slots=True)
class TurnEvent:
    event_id: str
    session_id: str
    sequence: int
    snapshot: TurnSnapshot

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id cannot be empty")
        if not self.session_id:
            raise ValueError("session_id cannot be empty")
        if self.sequence <= 0:
            raise ValueError("sequence must be positive")
