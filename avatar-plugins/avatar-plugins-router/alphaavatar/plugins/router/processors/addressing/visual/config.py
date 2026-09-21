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


class VisualAddressingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True

    toward_threshold: float = Field(default=0.72, ge=0.0, le=1.0)
    away_threshold: float = Field(default=0.35, ge=0.0, le=1.0)

    ema_alpha: float = Field(default=0.55, gt=0.0, le=1.0)
    min_samples: int = Field(default=2, gt=0)
    republish_interval_sec: float = Field(default=0.75, ge=0.0)

    publish_away_evidence: bool = True

    yaw_scale: float = Field(default=0.28, gt=0.0)
    roll_scale_deg: float = Field(default=25.0, gt=0.0)
    min_face_area_ratio: float = Field(default=0.01, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "VisualAddressingConfig":
        if self.away_threshold >= self.toward_threshold:
            raise ValueError("away_threshold must be smaller than toward_threshold")
        return self
