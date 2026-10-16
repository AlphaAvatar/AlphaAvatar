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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    on_session_end: Literal["finish_execution"] = "finish_execution"
    max_session_seconds: int = Field(default=1800, strict=True, ge=0)
    reservation_timeout: float = Field(default=15.0, strict=True, gt=0)
    ledger_capacity: int = Field(default=10000, strict=True, ge=1)

    def ends_execution(self) -> bool:
        return self.on_session_end == "finish_execution"
