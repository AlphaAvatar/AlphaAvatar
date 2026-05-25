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
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from alphaavatar.agents.status.enum import (
    StatusPriority,
    StatusType,
    StatusVisibility,
)

StatusRenderMode = Literal["auto", "template", "llm", "none"]


def _to_json_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value

    if isinstance(value, dict):
        return {k: _to_json_value(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_to_json_value(v) for v in value]

    if isinstance(value, tuple):
        return tuple(_to_json_value(v) for v in value)

    return value


@dataclass(slots=True)
class StatusEvent:
    type: StatusType
    source: str | StrEnum

    stage: str | StrEnum | None = None

    message: str | None = None
    message_key: str | None = None

    visibility: StatusVisibility = StatusVisibility.TEXT
    priority: StatusPriority = StatusPriority.NORMAL

    # auto:
    #   Let renderer choose template or llm.
    # template:
    #   Force deterministic template rendering.
    # llm:
    #   Force small-model rendering.
    # none:
    #   Structured event only.
    render_mode: StatusRenderMode = "auto"

    # Optional language hint.
    # Example: "en", "zh", "ja", "ar".
    # If None, renderer falls back to its default language.
    language: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "source": _to_json_value(self.source),
            "stage": _to_json_value(self.stage),
            "message": self.message,
            "message_key": self.message_key,
            "visibility": self.visibility.value,
            "priority": self.priority.value,
            "render_mode": self.render_mode,
            "language": self.language,
            "metadata": _to_json_value(self.metadata),
            "created_at": self.created_at,
        }
