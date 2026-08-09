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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaavatar.agents.constants import VIDEO_VISION_INTERVAL_SEC
from alphaavatar.agents.providers.schema import ModelInputType


class VisionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    input_mode: ModelInputType = ModelInputType.TEXT
    sample_interval_sec: float = Field(default=VIDEO_VISION_INTERVAL_SEC, gt=0, le=10.0)
    max_frames: int = Field(default=4, ge=1, le=32)

    @model_validator(mode="after")
    def normalize(self) -> VisionConfig:
        if not self.enabled:
            self.input_mode = ModelInputType.TEXT
        elif self.input_mode == ModelInputType.TEXT:
            self.enabled = False
        return self
