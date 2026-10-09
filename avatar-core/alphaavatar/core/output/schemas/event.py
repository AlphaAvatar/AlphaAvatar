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

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from ..enums import OutputKind, OutputLane
from .records import OutputScope

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class OutputEvent:
    """One item on the delivery timeline; record and execution journals have local sequences."""

    event_id: str
    sequence: int
    session_id: str
    created_at: float
    monotonic_ns: int
    kind: OutputKind
    lane: OutputLane
    output_id: str | None = None
    turn_id: str | None = None
    payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_control(self) -> bool:
        return self.kind == OutputKind.CONTROL


@dataclass(frozen=True, slots=True)
class OutputJournalEvent(Generic[T]):
    event_id: str
    sequence: int
    session_id: str
    created_at: float
    monotonic_ns: int
    key: str
    scope: OutputScope
    payload: T
    digest: str
    size_bytes: int
