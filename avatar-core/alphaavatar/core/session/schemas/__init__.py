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

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from alphaavatar.core.time import RuntimeTime

from ..enums import IdentitySource, SessionEventKind


def validate_identity(value: str, *, name: str = "identity") -> str:
    """Validate a logical identity without rewriting it or imposing path syntax."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or value != value.strip() or not value.isprintable():
        raise ValueError(f"{name} must be nonempty, printable and have no surrounding whitespace")
    return value


def _validate_sequence(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class Participant:
    participant_id: str
    user_id: str
    joined_at: RuntimeTime
    resolved_user_id: str | None = None
    identity_sequence: int = 0
    timezone: str | None = None

    def __post_init__(self) -> None:
        validate_identity(self.participant_id, name="participant_id")
        validate_identity(self.user_id, name="user_id")
        if self.resolved_user_id is not None:
            validate_identity(self.resolved_user_id, name="resolved_user_id")
        if not isinstance(self.joined_at, RuntimeTime):
            raise TypeError("joined_at must be RuntimeTime")
        _validate_sequence(self.identity_sequence, name="identity_sequence")
        if self.timezone is not None:
            validate_identity(self.timezone, name="timezone")

    @property
    def effective_user_id(self) -> str:
        return self.resolved_user_id or self.user_id


@dataclass(frozen=True, slots=True)
class IdentityRequest:
    participant_id: str
    user_id: str | None
    source: IdentitySource
    basis_sequence: int
    score: float | None = None

    def __post_init__(self) -> None:
        validate_identity(self.participant_id, name="participant_id")
        if self.user_id is not None:
            validate_identity(self.user_id, name="user_id")
        if not isinstance(self.source, IdentitySource):
            raise TypeError("source must be IdentitySource")
        _validate_sequence(self.basis_sequence, name="basis_sequence")
        if self.score is not None and (
            isinstance(self.score, bool) or not math.isfinite(self.score)
        ):
            raise ValueError("score must be finite")


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


__all__ = ["IdentityRequest", "Participant", "SessionEvent", "SessionSnapshot", "SessionStreamRead"]
