# Copyright 2025 AlphaAvatar project
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

from alphaavatar.core.perception import TemporalAlignmentMode, TemporalAlignmentPolicy


class TemporalAlignmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: TemporalAlignmentMode = TemporalAlignmentMode.AUTO
    interval_sec: float = Field(default=1.0, gt=0, le=10.0)
    min_interval_sec: float = Field(default=0.5, gt=0, le=10.0)
    max_interval_sec: float = Field(default=2.0, gt=0, le=30.0)
    speech_context_sec: float = Field(default=0.5, ge=0, le=5.0)
    include_gap_slices: bool = True

    @model_validator(mode="after")
    def validate_intervals(self) -> TemporalAlignmentConfig:
        if not self.min_interval_sec <= self.interval_sec <= self.max_interval_sec:
            raise ValueError("interval_sec must be between min_interval_sec and max_interval_sec")
        return self

    def build_policy(self, *, mode: TemporalAlignmentMode | None = None) -> TemporalAlignmentPolicy:
        return TemporalAlignmentPolicy(
            mode=mode or self.mode,
            interval_sec=self.interval_sec,
            min_interval_sec=self.min_interval_sec,
            max_interval_sec=self.max_interval_sec,
            speech_context_sec=self.speech_context_sec,
            include_gap_slices=self.include_gap_slices,
        )


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temporal_alignment: TemporalAlignmentConfig = Field(default_factory=TemporalAlignmentConfig)
