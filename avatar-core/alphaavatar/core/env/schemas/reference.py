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
from typing import Any


def _validate_id(name: str, value: str) -> None:
    if not value:
        raise ValueError(f"{name} cannot be empty")


@dataclass(frozen=True, slots=True)
class PerceptionSourceRef:
    source_id: str
    source_generation: int

    def __post_init__(self) -> None:
        _validate_id("source_id", self.source_id)
        if self.source_generation <= 0:
            raise ValueError("source_generation must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_generation": self.source_generation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerceptionSourceRef:
        return cls(
            source_id=str(data["source_id"]),
            source_generation=int(data["source_generation"]),
        )


@dataclass(frozen=True, slots=True)
class PerceptionSegmentRef:
    source: PerceptionSourceRef
    segment_id: str

    def __post_init__(self) -> None:
        _validate_id("segment_id", self.segment_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "segment_id": self.segment_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerceptionSegmentRef:
        return cls(
            source=PerceptionSourceRef.from_dict(data["source"]),
            segment_id=str(data["segment_id"]),
        )


@dataclass(frozen=True, slots=True)
class PerceptionEntityRef:
    perception_entity_id: str
    resolved_entity_id: str | None = None

    def __post_init__(self) -> None:
        _validate_id("perception_entity_id", self.perception_entity_id)
        if self.resolved_entity_id == "":
            raise ValueError("resolved_entity_id cannot be empty")

    def to_dict(self) -> dict[str, str]:
        data = {"perception_entity_id": self.perception_entity_id}
        if self.resolved_entity_id is not None:
            data["resolved_entity_id"] = self.resolved_entity_id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerceptionEntityRef:
        return cls(
            perception_entity_id=str(data["perception_entity_id"]),
            resolved_entity_id=data.get("resolved_entity_id"),
        )
