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

from alphaavatar.core.perception import (
    PerceptionRetentionPolicy,
    PerceptionStreamKind,
    TemporalAlignmentMode,
    TemporalAlignmentPolicy,
)


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


class PerceptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_sec: float = Field(default=60.0, gt=0, le=600.0)
    headroom: float = Field(default=1.25, ge=1.0, le=4.0)

    video_publish_interval_sec: float = Field(default=0.1, gt=0, le=10.0)
    audio_frame_size_ms: int = Field(default=20, gt=0, le=1000)

    text_maxlen: int = Field(default=1024, gt=0)
    event_maxlen: int = Field(default=8192, gt=0)

    def build_stream_maxlens(self) -> dict[PerceptionStreamKind, int]:
        policy = PerceptionRetentionPolicy(
            retention_sec=self.retention_sec,
            headroom=self.headroom,
        )
        audio_interval_sec = self.audio_frame_size_ms / 1000

        return {
            PerceptionStreamKind.VIDEO: policy.capacity(self.video_publish_interval_sec),
            PerceptionStreamKind.SCREEN: policy.capacity(self.video_publish_interval_sec),
            PerceptionStreamKind.AUDIO: policy.capacity(audio_interval_sec),
            PerceptionStreamKind.SPEECH: policy.capacity(audio_interval_sec),
            PerceptionStreamKind.TEXT: self.text_maxlen,
            PerceptionStreamKind.ANNOTATION: self.event_maxlen,
            PerceptionStreamKind.EVENT: self.event_maxlen,
        }


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temporal_alignment: TemporalAlignmentConfig = Field(default_factory=TemporalAlignmentConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
