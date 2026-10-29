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

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from alphaavatar.core.time import RuntimeTime

from ..enums import IdentitySource, SessionEventKind
from .participant import Participant


@dataclass(frozen=True, slots=True)
class SessionEvent:
    session_id: str
    sequence: int
    kind: SessionEventKind
    at: RuntimeTime
    participant: Participant | None = None
    previous_user_id: str | None = None
    source: IdentitySource | None = None
    primary_participant_id: str | None = None
    reason: str | None = None
    score: float | None = None


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: str
    sequence: int
    primary_participant_id: str | None
    participants: Mapping[str, Participant]
    closed: bool
    created_at: RuntimeTime

    def __post_init__(self) -> None:
        object.__setattr__(self, "participants", MappingProxyType(dict(self.participants)))


@dataclass(frozen=True, slots=True)
class SessionStreamRead:
    items: tuple[SessionEvent, ...]
    cursor_seq: int
    committed_cursor_seq: int
    first_available_seq: int | None
    latest_seq: int
    missed_count: int = 0
    closed: bool = False

    @property
    def has_gap(self) -> bool:
        return self.missed_count > 0

    @property
    def remaining_count(self) -> int:
        return max(0, self.latest_seq - self.cursor_seq)
