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


class AudioActivityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    pre_roll_sec: float = Field(default=0.3, ge=0.0)
    max_buffer_sec: float = Field(default=2.0, gt=0.0)

    @model_validator(mode="after")
    def validate_buffer(self) -> "AudioActivityConfig":
        if self.max_buffer_sec < self.pre_roll_sec:
            raise ValueError("max_buffer_sec cannot be smaller than pre_roll_sec")
        return self
