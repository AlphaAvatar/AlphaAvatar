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
from typing import Literal, TypeAlias

from ..enums import ModelFinishReason, ModelMessagePhase
from .model_input import ModelFunctionCall, ModelInputMessage
from .provider_item import ModelProviderItem
from .usage import ProviderUsage

ModelOutputItem: TypeAlias = ModelInputMessage | ModelFunctionCall | ModelProviderItem


@dataclass(frozen=True, slots=True, kw_only=True)
class _ResponseEvent:
    request_id: str
    response_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelResponseStarted(_ResponseEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelItemStarted(_ResponseEvent):
    item_id: str
    output_index: int
    kind: Literal["message", "function_call", "reasoning"]
    phase: ModelMessagePhase | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class _ContentDelta(_ResponseEvent):
    item_id: str
    output_index: int
    content_index: int
    text: str
    phase: ModelMessagePhase | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelTextDelta(_ContentDelta):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelRefusalDelta(_ContentDelta):
    """Refusal text, kept distinct from a normal answer."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelReasoningDelta(_ContentDelta):
    """Provider summary only. Consumers must not send it to ordinary speech/text output."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelToolCallDelta(_ResponseEvent):
    item_id: str
    output_index: int
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelItemCompleted(_ResponseEvent):
    output_index: int
    item: ModelOutputItem


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelResponseCompleted(_ResponseEvent):
    items: tuple[ModelOutputItem, ...]
    finish_reason: ModelFinishReason
    usage: ProviderUsage | None = None


ModelStreamEvent: TypeAlias = (
    ModelResponseStarted
    | ModelItemStarted
    | ModelTextDelta
    | ModelRefusalDelta
    | ModelReasoningDelta
    | ModelToolCallDelta
    | ModelItemCompleted
    | ModelResponseCompleted
)
