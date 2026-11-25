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


@dataclass(frozen=True, slots=True)
class InferenceRunnerStatus:
    """Startup history is separate from current readiness; neither proves tool success.

    ``ready`` means every configured worker is ready; fewer ``ready_workers`` is degraded
    service that still admits requests. Counters never carry request or model content.
    """

    method: str
    startup_state: Literal["pending", "initializing", "ready", "failed", "cancelled"] = "pending"
    ready: bool = False
    startup_elapsed_seconds: float | None = None
    error_type: str | None = None
    workers: int = 1
    ready_workers: int = 0
    executing: int = 0
    waiting: int = 0
    rejected: int = 0
    queue_timeouts: int = 0
    execution_timeouts: int = 0
    restarts: int = 0
