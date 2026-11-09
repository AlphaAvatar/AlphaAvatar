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


class AddressingFusionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_margin: float = Field(default=0.1, ge=0.0, le=1.0)


class TurnTakingModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "smart_turn_v3"
    incomplete_threshold: float = Field(default=0.3, ge=0.0, le=1.0, allow_inf_nan=False)
    complete_threshold: float = Field(default=0.7, ge=0.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _validate_thresholds(self) -> TurnTakingModelConfig:
        if self.incomplete_threshold >= self.complete_threshold:
            raise ValueError("incomplete_threshold must be less than complete_threshold")
        return self


class TurnTakingPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    respond_to_group: bool = False


class TurnTakingInterruptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    audio_only_speech_start: bool = True


class TurnTakingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True

    addressing_wait_sec: float = Field(default=0.5, gt=0.0, allow_inf_nan=False)

    # Report a pending transcript after the soft threshold; only the hard deadline retires it.
    transcript_wait_sec: float = Field(default=0.75, ge=0.0, allow_inf_nan=False)
    transcript_timeout_sec: float = Field(default=3.0, gt=0.0, allow_inf_nan=False)

    unsegmented_alignment_sec: float = Field(default=0.75, gt=0.0)
    completion_wait_sec: float = Field(default=1.5, gt=0.0, allow_inf_nan=False)
    commit_timeout_sec: float = Field(default=3.0, gt=0.0, allow_inf_nan=False)
    max_pending_inputs: int = Field(default=128, ge=1, le=4096)
    max_window_segments: int = Field(default=128, ge=1, le=4096)

    fusion: AddressingFusionConfig = Field(default_factory=AddressingFusionConfig)
    model: TurnTakingModelConfig = Field(default_factory=TurnTakingModelConfig)
    policy: TurnTakingPolicyConfig = Field(default_factory=TurnTakingPolicyConfig)
    interruption: TurnTakingInterruptionConfig = Field(default_factory=TurnTakingInterruptionConfig)
