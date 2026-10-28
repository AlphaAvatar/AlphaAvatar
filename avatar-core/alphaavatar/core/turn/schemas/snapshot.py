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
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from alphaavatar.core.perception.schemas import PerceptionCutoff, PerceptionEvent
from alphaavatar.core.time import RuntimeTime

from ..enums import TurnInputModality
from .reference import TurnEntityRef


@dataclass(frozen=True, slots=True)
class TurnSnapshot:
    turn_id: str
    input_id: str
    modality: TurnInputModality
    text: str | None

    input_observation_ids: tuple[str, ...]

    started_at: RuntimeTime
    committed_at: RuntimeTime

    start_cutoff: PerceptionCutoff
    cutoff: PerceptionCutoff
    perception_events: tuple[PerceptionEvent, ...]
    perception_gap: bool = False
    missed_perception_events: int = 0

    actors: tuple[TurnEntityRef, ...] = ()
    addressees: tuple[TurnEntityRef, ...] = ()
    context_ids: tuple[str, ...] = ()

    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.turn_id:
            raise ValueError("turn_id cannot be empty")
        if not self.input_id:
            raise ValueError("input_id cannot be empty")

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
