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
from dataclasses import replace
from types import MappingProxyType
from typing import Any, TypeAlias

from alphaavatar.agents.avatar.provider.enums import ModelMessagePhase, ModelRole
from alphaavatar.agents.avatar.provider.schemas.model_input import (
    ModelAudioPart,
    ModelControlItem,
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelImagePart,
    ModelInputItem,
    ModelInputMessage,
    ModelMediaPart,
    ModelProviderItem,
    ModelReasoningPart,
    ModelRefusalPart,
    ModelTemporalPart,
    ModelTextPart,
)
from alphaavatar.agents.constants import RUNTIME_CONTEXT_TOOL_NAME

MemoryMessage: TypeAlias = ModelInputMessage | ModelFunctionCall | ModelFunctionOutput


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


def memory_message(item: ModelInputItem) -> MemoryMessage | None:
    """Project evidence for extraction, not Provider continuation or application instructions."""
    if isinstance(item, ModelControlItem | ModelProviderItem):
        return None
    if not isinstance(item, ModelInputMessage | ModelFunctionCall | ModelFunctionOutput):
        raise TypeError("Memory requires native model items")
    if not isinstance(item.id, str) or not item.id.strip():
        raise ValueError("Memory messages require a nonempty identity")
    if isinstance(item, ModelInputMessage):
        if not isinstance(item.role, ModelRole):
            raise TypeError("Memory message roles must use ModelRole")
        if item.phase is not None and not isinstance(item.phase, ModelMessagePhase):
            raise TypeError("Memory message phases must use ModelMessagePhase")
        # Turns are the sole user-input source. Never promote system instructions to memories.
        if item.role != ModelRole.ASSISTANT:
            return None
    else:
        if item.name == RUNTIME_CONTEXT_TOOL_NAME:
            return None
        if not all(isinstance(value, str) and value.strip() for value in (item.call_id, item.name)):
            raise ValueError("Memory tool records require call and tool identities")
        if isinstance(item, ModelFunctionCall) and not isinstance(item.arguments, str):
            raise TypeError("Memory tool arguments must be serialized text")
        if isinstance(item, ModelFunctionOutput) and type(item.is_error) is not bool:
            raise TypeError("Memory tool errors must be explicit booleans")

    changes: dict[str, Any] = {}
    if isinstance(item, ModelInputMessage | ModelFunctionCall):
        if not isinstance(item.metadata, Mapping):
            raise TypeError("Memory record metadata must be a mapping")
        changes["metadata"] = _freeze(item.metadata)
    if isinstance(item, ModelInputMessage | ModelFunctionOutput):
        parts = []
        for part in item.parts:
            if isinstance(part, ModelReasoningPart):
                continue
            if isinstance(part, ModelTextPart | ModelRefusalPart) and not isinstance(
                part.text, str
            ):
                raise TypeError("Memory text parts must contain strings")
            if isinstance(part, ModelTextPart):
                annotations = tuple(_freeze(value) for value in part.annotations)
                part = replace(part, annotations=annotations)
            elif not isinstance(
                part,
                ModelRefusalPart
                | ModelImagePart
                | ModelAudioPart
                | ModelTemporalPart
                | ModelMediaPart,
            ):
                raise TypeError("Unsupported memory content part")
            parts.append(part)
        if not parts and isinstance(item, ModelInputMessage):
            return None
        changes["parts"] = tuple(parts)
    return replace(item, **changes)


def _part_key(part: Any) -> Any:
    # Core observations are identified by their immutable evidence identity, not decoded pixels.
    if isinstance(part, ModelImagePart | ModelAudioPart):
        return type(part), part.observation.observation_id
    if isinstance(part, ModelTemporalPart):
        return type(part), tuple(
            (
                value.index,
                value.time_range,
                tuple(item.observation_id for item in value.observations),
                tuple(event.event_id for event in value.source_events),
            )
            for value in part.slices
        )
    return part


def same_message(left: MemoryMessage, right: MemoryMessage) -> bool:
    """Detect conflicting replay without encoding or hashing large media payloads."""
    if type(left) is not type(right) or left.id != right.id:
        return False
    if isinstance(left, ModelInputMessage):
        return (
            left.role == right.role
            and left.phase == right.phase
            and left.interrupted == right.interrupted
            and left.transcript_confidence == right.transcript_confidence
            and left.created_at == right.created_at
            and left.metadata == right.metadata
            and tuple(map(_part_key, left.parts)) == tuple(map(_part_key, right.parts))
        )
    if isinstance(left, ModelFunctionCall):
        return left == right
    return (
        left.call_id == right.call_id
        and left.name == right.name
        and left.is_error == right.is_error
        and left.created_at == right.created_at
        and tuple(map(_part_key, left.parts)) == tuple(map(_part_key, right.parts))
    )
