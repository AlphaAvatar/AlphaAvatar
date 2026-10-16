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
from typing import Literal

ExecutionState = Literal[
    "reserved", "starting", "running", "stopping", "success", "failed", "unknown", "cancelled"
]
TERMINAL_STATES = frozenset(("success", "failed", "unknown", "cancelled"))


@dataclass(frozen=True, slots=True)
class ExecutionReservation:
    execution_id: str
    attachment_id: str
    backend: str
    source_id: str
    lease_id: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class ExecutionView:
    execution_id: str
    backend: str
    source_id: str
    state: ExecutionState
    reason: str
    pid: int | None
