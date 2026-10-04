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

from alphaavatar.agents.avatar.provider.schemas import ModelInputMessage
from alphaavatar.agents.avatar.provider.schemas.stream import ModelTextDelta

from ..enums import LoopEventKind, LoopState, ToolOutcome
from .identity import LoopIdentity


@dataclass(frozen=True, slots=True)
class LoopEvent:
    """Public feedback. Opaque continuation and reasoning are not UI content."""

    identity: LoopIdentity
    sequence: int
    kind: LoopEventKind

    state: LoopState
    model_step: int = 0
    tool_round: int = 0

    text: ModelTextDelta | None = None
    message: ModelInputMessage | None = None

    call_id: str | None = None
    tool_name: str | None = None
    outcome: ToolOutcome | None = None
    reason: str | None = None
