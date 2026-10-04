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

from alphaavatar.agents.avatar.provider.schemas import (
    ModelInputItem,
    ModelInputMessage,
)

from ..enums import LoopState
from .identity import LoopIdentity
from .tool import ToolRecord


@dataclass(frozen=True, slots=True)
class LoopResult:
    identity: LoopIdentity
    state: LoopState
    items: tuple[ModelInputItem, ...]
    final_messages: tuple[ModelInputMessage, ...]
    tools: tuple[ToolRecord, ...]
    model_steps: int
    tool_rounds: int
    elapsed_ms: float
    reason: str | None = None
    error_type: str | None = None
