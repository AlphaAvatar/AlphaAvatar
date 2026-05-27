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
from typing import Any

from alphaavatar.agents.status.enum import (
    StatusPriority,
    StatusType,
)


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

    # Short user-facing status text.
    # If provided, renderer should use it directly.
    message: str | None = None

    priority: StatusPriority = StatusPriority.NORMAL

    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "source": _to_json_value(self.source),
            "stage": _to_json_value(self.stage),
            "message": self.message,
            "priority": self.priority.value,
            "metadata": _to_json_value(self.metadata),
            "created_at": self.created_at,
        }
