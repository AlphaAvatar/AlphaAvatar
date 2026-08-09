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

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from alphaavatar.core.env import EnvObservation
from alphaavatar.core.perception import (
    PerceptionCutoff,
    PerceptionEvent,
    PerceptionRuntime,
)
from alphaavatar.core.time import RuntimeTime


class TurnInputModality(StrEnum):
    SYSTEM = "system"
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    MULTIMODAL = "multimodal"


@dataclass(frozen=True, slots=True)
class TurnSnapshot:
    turn_id: str
    input_id: str
    modality: TurnInputModality
    text: str | None

    started_at: RuntimeTime
    committed_at: RuntimeTime

    start_cutoff: PerceptionCutoff
    cutoff: PerceptionCutoff
    perception_events: tuple[PerceptionEvent, ...]

    perception_gap: bool = False
    missed_perception_events: int = 0
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def start_sequence(self) -> int:
        return self.start_cutoff.sequence

    @property
    def cutoff_sequence(self) -> int:
        return self.cutoff.sequence

    @property
    def source_states_at_start(self):
        return self.start_cutoff.sources

    @property
    def source_states_at_commit(self):
        return self.cutoff.sources


class TurnRuntime:
    """
    Session-scoped immutable user-turn registry.

    A turn is committed once for one input_id. Model retries and tool-response
    generations reuse the same TurnSnapshot.
    """

    _DIRECT_TEXT_MODALITIES = {
        TurnInputModality.TEXT,
        TurnInputModality.MULTIMODAL,
    }

    def __init__(
        self,
        *,
        perception: PerceptionRuntime,
        max_snapshots: int = 128,
    ) -> None:
        if max_snapshots <= 0:
            raise ValueError("max_snapshots must be positive")

        self._perception = perception
        self._max_snapshots = max_snapshots
        self._snapshots: OrderedDict[str, TurnSnapshot] = OrderedDict()
        self._last_cutoff = perception.capture_cutoff()

    @property
    def latest(self) -> TurnSnapshot | None:
        return next(reversed(self._snapshots.values()), None)

    @property
    def perception(self) -> PerceptionRuntime:
        return self._perception

    def get(self, input_id: str) -> TurnSnapshot | None:
        return self._snapshots.get(input_id)

    def commit_input(
        self,
        *,
        input_id: str,
        modality: TurnInputModality,
        text: str | None = None,
        final_observations: Sequence[EnvObservation] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> TurnSnapshot:
        if not input_id:
            raise ValueError("input_id cannot be empty")
        if existing := self._snapshots.get(input_id):
            return existing

        start_cutoff = self._last_cutoff
        perception = self._perception.capture_snapshot(
            after_sequence=start_cutoff.sequence,
            final_observations=final_observations,
        )
        snapshot = TurnSnapshot(
            turn_id=uuid4().hex,
            input_id=input_id,
            modality=modality,
            text=text,
            started_at=start_cutoff.captured_at,
            committed_at=perception.cutoff.captured_at,
            start_cutoff=start_cutoff,
            cutoff=perception.cutoff,
            perception_events=perception.events,
            perception_gap=perception.has_gap,
            missed_perception_events=perception.missed_count,
            metadata=MappingProxyType(dict(metadata or {})),
        )
        self._snapshots[input_id] = snapshot
        self._last_cutoff = perception.cutoff
        while len(self._snapshots) > self._max_snapshots:
            self._snapshots.popitem(last=False)
        return snapshot

    def clear(self) -> None:
        self._snapshots.clear()
        self._last_cutoff = self._perception.capture_cutoff()
