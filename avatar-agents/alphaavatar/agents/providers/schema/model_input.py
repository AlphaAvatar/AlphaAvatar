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
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeAlias

from alphaavatar.core.env import EnvObservation
from alphaavatar.core.perception import AlignedPerception, PerceptionEvent
from alphaavatar.core.time import RuntimeTimeRange

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.vision import VisualSelection


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


class ModelInputType(StrEnum):
    TEXT = "text"
    VLM = "vlm"
    REALTIME = "realtime"


class ModelRole(StrEnum):
    DEVELOPER = "developer"
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ModelTextPart:
    text: str


@dataclass(frozen=True, slots=True)
class ModelImagePart:
    observation: EnvObservation


@dataclass(frozen=True, slots=True)
class ModelAudioPart:
    observation: EnvObservation


@dataclass(frozen=True, slots=True)
class ModelTemporalSlice:
    index: int
    time_range: RuntimeTimeRange
    observations: tuple[EnvObservation, ...]
    source_events: tuple[PerceptionEvent, ...]


@dataclass(frozen=True, slots=True)
class ModelTemporalPart:
    """
    Provider-neutral time-aligned multimodal input.

    Providers decide how to encode it:
    - Gemini batch: continuous audio track + timestamped images;
    - Qwen Omni: native audio/video patches and timestamps;
    - realtime providers: streamed media events.
    """

    alignment: AlignedPerception
    slices: tuple[ModelTemporalSlice, ...]

    @property
    def observations(self) -> tuple[EnvObservation, ...]:
        by_id = {
            observation.observation_id: observation
            for temporal_slice in self.slices
            for observation in temporal_slice.observations
        }
        return tuple(
            sorted(
                by_id.values(),
                key=lambda item: (
                    item.time_range.start.monotonic_ns,
                    item.time_range.end.monotonic_ns,
                    item.observation_id,
                ),
            )
        )


ModelInputPart: TypeAlias = ModelTextPart | ModelImagePart | ModelAudioPart | ModelTemporalPart


@dataclass(frozen=True, slots=True)
class ModelInputMessage:
    id: str
    role: ModelRole
    parts: tuple[ModelInputPart, ...]
    interrupted: bool = False
    transcript_confidence: float | None = None
    created_at: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping)

    @property
    def text(self) -> str | None:
        values = [part.text for part in self.parts if isinstance(part, ModelTextPart)]
        return "\n".join(values) if values else None


@dataclass(frozen=True, slots=True)
class ModelFunctionCall:
    id: str
    call_id: str
    name: str
    arguments: str
    created_at: float | None = None
    group_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping)


@dataclass(frozen=True, slots=True)
class ModelFunctionOutput:
    id: str
    call_id: str
    name: str
    output: str
    is_error: bool
    created_at: float | None = None


@dataclass(frozen=True, slots=True)
class ModelControlItem:
    id: str
    kind: str
    data: Mapping[str, Any] = field(default_factory=_empty_mapping)
    created_at: float | None = None


ModelInputItem: TypeAlias = (
    ModelInputMessage | ModelFunctionCall | ModelFunctionOutput | ModelControlItem
)


@dataclass(frozen=True, slots=True)
class RealtimeModelInput:
    alignment: AlignedPerception
    visual_selection: VisualSelection
    direct_inputs: tuple[EnvObservation, ...]


@dataclass(frozen=True, slots=True)
class ModelInput:
    items: tuple[ModelInputItem, ...]
    realtime: RealtimeModelInput | None = None

    def get(self, item_id: str) -> ModelInputItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def replace(self, item_id: str, replacement: ModelInputItem) -> ModelInput:
        return replace(
            self,
            items=tuple(replacement if item.id == item_id else item for item in self.items),
        )

    def remove(self, item_id: str) -> ModelInput:
        return replace(self, items=tuple(item for item in self.items if item.id != item_id))

    def append(self, item: ModelInputItem) -> ModelInput:
        return replace(self, items=(*self.items, item))

    @property
    def latest_input_kind(self) -> str | None:
        for item in reversed(self.items):
            if isinstance(item, ModelInputMessage):
                return item.role.value
            if isinstance(item, ModelFunctionOutput):
                return "tool_output"
            if isinstance(item, ModelFunctionCall):
                return "tool_call"
        return None
