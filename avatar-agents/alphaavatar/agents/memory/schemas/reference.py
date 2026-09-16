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

from pydantic import BaseModel, field_validator, model_validator

from alphaavatar.core.env import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)

from ..enums import (
    MemoryOwnerKind,
    MemoryParticipantKind,
    MemorySourceKind,
)


def _normalize_id(value: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError("id cannot be empty")
    return value


class MemoryOwnerRef(BaseModel):
    kind: MemoryOwnerKind
    id: str

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _normalize_id(value)

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.id}"

    @classmethod
    def user(cls, user_id: str) -> MemoryOwnerRef:
        return cls(kind=MemoryOwnerKind.USER, id=user_id)

    @classmethod
    def avatar(cls, avatar_id: str) -> MemoryOwnerRef:
        return cls(kind=MemoryOwnerKind.AVATAR, id=avatar_id)


class MemoryParticipantRef(BaseModel):
    kind: MemoryParticipantKind
    id: str

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _normalize_id(value)

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.id}"

    @classmethod
    def user(cls, user_id: str) -> MemoryParticipantRef:
        return cls(kind=MemoryParticipantKind.USER, id=user_id)

    @classmethod
    def avatar(cls, avatar_id: str) -> MemoryParticipantRef:
        return cls(kind=MemoryParticipantKind.AVATAR, id=avatar_id)

    @classmethod
    def tool(cls, tool_id: str) -> MemoryParticipantRef:
        return cls(kind=MemoryParticipantKind.TOOL, id=tool_id)

    @classmethod
    def entity(cls, entity_id: str) -> MemoryParticipantRef:
        return cls(kind=MemoryParticipantKind.ENTITY, id=entity_id)


class MemorySourceRef(BaseModel):
    kind: MemorySourceKind
    source_id: str

    source_generation: int | None = None
    segment_id: str | None = None

    tool_id: str | None = None
    resolved_entity_id: str | None = None

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str) -> str:
        return _normalize_id(value)

    @field_validator("segment_id", "tool_id", "resolved_entity_id")
    @classmethod
    def _validate_optional_id(cls, value: str | None) -> str | None:
        return _normalize_id(value) if value is not None else None

    @model_validator(mode="after")
    def _validate_shape(self) -> MemorySourceRef:
        perception = {
            MemorySourceKind.PERCEPTION_SOURCE,
            MemorySourceKind.PERCEPTION_SEGMENT,
        }
        tool = {
            MemorySourceKind.TOOL_CALL,
            MemorySourceKind.TOOL_RESULT,
        }

        if self.kind in perception:
            if self.source_generation is None or self.source_generation <= 0:
                raise ValueError("perception source_generation must be positive")
        elif self.source_generation is not None:
            raise ValueError("source_generation is only valid for perception source/segment refs")

        if self.kind is MemorySourceKind.PERCEPTION_SEGMENT:
            if self.segment_id is None:
                raise ValueError("perception segment ref requires segment_id")
        elif self.segment_id is not None:
            raise ValueError("segment_id is only valid for perception segment refs")

        if self.kind in tool:
            if self.tool_id is None:
                raise ValueError("tool ref requires tool_id")
        elif self.tool_id is not None:
            raise ValueError("tool_id is only valid for tool refs")

        if (
            self.kind is not MemorySourceKind.PERCEPTION_ENTITY
            and self.resolved_entity_id is not None
        ):
            raise ValueError("resolved_entity_id is only valid for perception entity refs")

        return self

    @property
    def key(self) -> str:
        if self.kind in {
            MemorySourceKind.TOOL_CALL,
            MemorySourceKind.TOOL_RESULT,
        }:
            return f"{self.kind.value}:{self.tool_id}:{self.source_id}"

        if self.kind is MemorySourceKind.PERCEPTION_SOURCE:
            return f"{self.kind.value}:{self.source_id}:{self.source_generation}"

        if self.kind is MemorySourceKind.PERCEPTION_SEGMENT:
            return f"{self.kind.value}:{self.source_id}:{self.source_generation}:{self.segment_id}"

        return f"{self.kind.value}:{self.source_id}"

    @classmethod
    def message(cls, message_id: str) -> MemorySourceRef:
        return cls(kind=MemorySourceKind.MESSAGE, source_id=message_id)

    @classmethod
    def tool_call(cls, tool_id: str, call_id: str) -> MemorySourceRef:
        return cls(
            kind=MemorySourceKind.TOOL_CALL,
            source_id=call_id,
            tool_id=tool_id,
        )

    @classmethod
    def tool_result(cls, tool_id: str, call_id: str) -> MemorySourceRef:
        return cls(
            kind=MemorySourceKind.TOOL_RESULT,
            source_id=call_id,
            tool_id=tool_id,
        )

    @classmethod
    def perception_source(
        cls,
        ref: PerceptionSourceRef,
    ) -> MemorySourceRef:
        return cls(
            kind=MemorySourceKind.PERCEPTION_SOURCE,
            source_id=ref.source_id,
            source_generation=ref.source_generation,
        )

    @classmethod
    def perception_segment(
        cls,
        ref: PerceptionSegmentRef,
    ) -> MemorySourceRef:
        return cls(
            kind=MemorySourceKind.PERCEPTION_SEGMENT,
            source_id=ref.source.source_id,
            source_generation=ref.source.source_generation,
            segment_id=ref.segment_id,
        )

    @classmethod
    def perception_entity(
        cls,
        ref: PerceptionEntityRef,
    ) -> MemorySourceRef:
        return cls(
            kind=MemorySourceKind.PERCEPTION_ENTITY,
            source_id=ref.perception_entity_id,
            resolved_entity_id=ref.resolved_entity_id,
        )

    @classmethod
    def runtime_event(cls, event_id: str) -> MemorySourceRef:
        return cls(
            kind=MemorySourceKind.RUNTIME_EVENT,
            source_id=event_id,
        )
