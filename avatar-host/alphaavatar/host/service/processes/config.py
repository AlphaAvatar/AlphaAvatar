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


class ProcessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    capacity: int = Field(default=5, strict=True, ge=1, le=1024)
    startup_timeout: float = Field(default=120.0, strict=True, gt=0)
    shutdown_timeout: float = Field(default=180.0, strict=True, gt=0)
    terminate_timeout: float = Field(default=5.0, strict=True, gt=0)
    kill_timeout: float = Field(default=5.0, strict=True, gt=0)
    ipc_timeout: float = Field(default=5.0, strict=True, gt=0)
