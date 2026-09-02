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

from alphaavatar.agents.providers.schema import ModelInputType
from alphaavatar.core.env import EnvObservation


@dataclass(frozen=True, slots=True)
class SelectedVisualFrame:
    slice_index: int
    observation: EnvObservation


@dataclass(frozen=True, slots=True)
class VisualSliceSelection:
    slice_index: int
    frames: tuple[SelectedVisualFrame, ...]


@dataclass(frozen=True, slots=True)
class VisualSelection:
    input_type: ModelInputType
    slices: tuple[VisualSliceSelection, ...]

    @property
    def frames(self) -> tuple[SelectedVisualFrame, ...]:
        return tuple(frame for item in self.slices for frame in item.frames)

    @property
    def empty(self) -> bool:
        return not self.slices

    def for_slice(self, slice_index: int) -> tuple[SelectedVisualFrame, ...]:
        item = next((item for item in self.slices if item.slice_index == slice_index), None)
        return item.frames if item else ()
