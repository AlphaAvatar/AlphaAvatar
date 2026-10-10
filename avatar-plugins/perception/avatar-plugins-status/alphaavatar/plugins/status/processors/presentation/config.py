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
from pydantic import BaseModel, ConfigDict, Field


class PresentationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    waiting_delay: float = Field(default=1.5, ge=0, le=30, allow_inf_nan=False)
    min_narration_interval: float = Field(default=4.0, ge=0, le=120, allow_inf_nan=False)
    max_narrations_per_turn: int = Field(default=3, ge=0, le=20)
    decision_ttl: float = Field(default=5.0, gt=0, le=60, allow_inf_nan=False)
    publish_timeout: float = Field(default=0.5, gt=0, le=5, allow_inf_nan=False)
    system_decisions: bool = True
