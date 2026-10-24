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
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool = True
    passive_timeout_sec: float = Field(default=3.0, gt=0, le=30.0)
    max_pending_recalls: int = Field(default=8, ge=1, le=64)
    max_retained_turns: int = Field(default=32, ge=1, le=256)
    max_query_chars: int = Field(default=8192, ge=256, le=65536)

    search_context: int = Field(
        default=3, ge=1, le=32, description="The number of recent user Turns used for recall."
    )
    recall_num: int = Field(
        default=10, ge=1, le=64, description="The number of memory items to recall."
    )

    @model_validator(mode="after")
    def validate_capacity(self) -> "RetrievalConfig":
        if self.max_retained_turns < self.max_pending_recalls:
            raise ValueError("max_retained_turns must cover max_pending_recalls")
        return self
