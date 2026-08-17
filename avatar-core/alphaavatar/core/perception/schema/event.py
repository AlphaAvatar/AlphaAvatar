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
from typing import Any
from uuid import uuid4

from alphaavatar.core.env import EnvObservation
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange

from ..enum import (
    MediaModality,
    MediaSourceKind,
    MediaSourceState,
    PerceptionEventKind,
)


@dataclass(frozen=True, slots=True)
class MediaSourceStateEvent:
    source_id: str
    generation: int
    modality: MediaModality
    source_kind: MediaSourceKind
    state: MediaSourceState
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("Media source_id cannot be empty")
        if self.generation <= 0:
            raise ValueError("Media source generation must be positive")


@dataclass(frozen=True, slots=True)
class MediaSourceSnapshot:
    source_id: str
    generation: int
    modality: MediaModality
    source_kind: MediaSourceKind
    state: MediaSourceState
    changed_at: RuntimeTime
    changed_sequence: int
    latest_observation_at: RuntimeTime | None = None
    latest_observation_sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int]:
        return self.source_id, self.generation

    @property
    def available(self) -> bool:
        return self.state.available


@dataclass(frozen=True, slots=True)
class PerceptionEvent:
    session_id: str
    sequence: int
    time_range: RuntimeTimeRange
    kind: PerceptionEventKind
    payload: EnvObservation | MediaSourceStateEvent
    event_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("Perception event session_id cannot be empty")
        if self.sequence <= 0:
            raise ValueError("Perception event sequence must be positive")

    @property
    def observation(self) -> EnvObservation | None:
        return self.payload if isinstance(self.payload, EnvObservation) else None

    @property
    def source_state(self) -> MediaSourceStateEvent | None:
        return self.payload if isinstance(self.payload, MediaSourceStateEvent) else None


@dataclass(frozen=True, slots=True)
class PerceptionCutoff:
    sequence: int
    captured_at: RuntimeTime
    sources: tuple[MediaSourceSnapshot, ...]


@dataclass(frozen=True, slots=True)
class PerceptionSnapshot:
    after_sequence: int
    cutoff: PerceptionCutoff
    events: tuple[PerceptionEvent, ...]
    first_available_sequence: int | None
    missed_count: int = 0

    @property
    def has_gap(self) -> bool:
        return self.missed_count > 0
