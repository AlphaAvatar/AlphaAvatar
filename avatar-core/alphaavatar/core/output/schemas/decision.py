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

from ..enums.audience import OutputAudience
from .records import OutputScope


@dataclass(frozen=True, slots=True)
class OutputStatusDecision:
    """Derived presentation, never a new execution fact or a tool authorization."""

    decision_id: str
    source_event_id: str
    scope: OutputScope
    audience: OutputAudience
    action: str
    state: str
    revision: int
    expires_at_ns: int
    narration_key: str | None = None
    tool_name: str | None = None
    outcome: str | None = None
    terminal: bool = False

    def __post_init__(self) -> None:
        if type(self.terminal) is not bool:
            raise TypeError("Status terminal must be bool")
        if not isinstance(self.scope, OutputScope) or not isinstance(self.audience, OutputAudience):
            raise TypeError("Status decisions require a typed scope and audience")
        for name in ("decision_id", "source_event_id", "action", "state"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 2048:
                raise ValueError(f"Invalid status decision {name}")
        for value in (self.narration_key, self.tool_name, self.outcome):
            if value is not None and (not isinstance(value, str) or len(value) > 2048):
                raise ValueError("Status decision fields must be bounded strings")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("Status revision must be a nonnegative integer")
        if type(self.expires_at_ns) is not int or self.expires_at_ns < 0:
            raise ValueError("Status expiry must be a monotonic timestamp")
