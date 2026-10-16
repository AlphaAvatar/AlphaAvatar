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

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.host.execution.policy import ExecutionPolicy
from alphaavatar.host.processes.config import ProcessConfig
from alphaavatar.host.sessions.config import SessionConfig


class HealthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bind: str = "0.0.0.0"
    port: int | None = Field(default=None, strict=True, ge=0, le=65535)


class HostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    rtc: SessionConfig = Field(default_factory=SessionConfig)
    processes: ProcessConfig = Field(default_factory=ProcessConfig)
    execution: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    health: HealthConfig = Field(default_factory=HealthConfig)
    inference_check_interval: float = Field(default=0.5, strict=True, gt=0)
