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

type MemoryMessage = ModelInputMessage | ModelFunctionCall | ModelFunctionOutput


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

    changes = {}
    if isinstance(item, ModelInputMessage | ModelFunctionCall):
        if not isinstance(item.metadata, Mapping):
            raise TypeError("Memory record metadata must be a mapping")
        changes["metadata"] = MappingProxyType({})
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
                part = replace(part, annotations=())
            elif not isinstance(
                part,
                ModelRefusalPart
                | ModelImagePart
                | ModelAudioPart
                | ModelTemporalPart
                | ModelMediaPart,
            ):
                raise TypeError("Unsupported memory content part")
            if isinstance(part, ModelImagePart | ModelAudioPart):
                part = ModelTextPart(
                    f"[media evidence: observation={part.observation.observation_id}]"
                )
            elif isinstance(part, ModelTemporalPart):
                observations = ",".join(
                    observation.observation_id
                    for value in part.slices
                    for observation in value.observations
                )
                part = ModelTextPart(
                    f"[temporal evidence: observations={observations}; not decoded here]"
                )
            elif isinstance(part, ModelMediaPart):
                part = ModelTextPart(
                    f"[media evidence: {part.kind.value}, {part.mime_type}; not decoded here]"
                )
            parts.append(part)
        if not parts and isinstance(item, ModelInputMessage):
            return None
        changes["parts"] = tuple(parts)
    return replace(item, **changes)


def same_message(left: MemoryMessage, right: MemoryMessage) -> bool:
    """The compact buffer contains frozen text and scalar evidence only."""
    return type(left) is type(right) and left == right
