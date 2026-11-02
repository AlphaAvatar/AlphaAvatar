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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaavatar.agents.avatar.loop.schemas import LoopLimits
from alphaavatar.agents.constants import MAX_INFERENCE_WORKERS
from alphaavatar.core.perception import TemporalAlignmentMode, TemporalAlignmentPolicy
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.perception.schemas import PerceptionRetentionPolicy


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

    temporal_alignment: TemporalAlignmentConfig = Field(default_factory=TemporalAlignmentConfig)

    def build_stream_maxlens(self) -> dict[PerceptionStreamKind, int]:
        policy = PerceptionRetentionPolicy(retention_sec=self.retention_sec, headroom=self.headroom)
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


class TurnConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_maxlen: int = Field(default=128, gt=0)
    event_maxlen: int = Field(default=256, gt=0)
    context_ready_timeout_sec: float = Field(default=0.5, ge=0, le=10.0)


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_turn_candidates: int = Field(default=4096, ge=1)
    max_pending_admissions: int = Field(default=32, ge=1)
    max_input_bytes: int = Field(default=262144, ge=1)
    loop_limits: LoopLimits = Field(default_factory=LoopLimits)
    depth: Literal["auto", "quick", "careful"] = "auto"


class InferenceMethodConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Independent runner processes, each with its own model copy and memory. Opt-in only.
    workers: int = Field(default=1, strict=True, ge=1, le=MAX_INFERENCE_WORKERS)


class InferenceConfig(BaseModel):
    """Shared Runner service limits: the Host builds one pool from them, sessions only connect."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    # Per method across its workers: requests waiting for a worker plus those executing.
    max_pending: int = Field(default=64, strict=True, ge=1, le=1024)
    # Service: waiting for an idle worker. An expired or abandoned request never runs.
    queue_timeout: float = Field(default=30.0, strict=True, gt=0, le=600)
    # Service: one execution. Expiry retires that worker; the request is never replayed.
    request_timeout: float = Field(default=30.0, strict=True, gt=0, le=600)
    # Client: waiting for a free channel, then connect and send. The response wait is the
    # service's announced queue, execution and settlement budget, not this value.
    client_timeout: float = Field(default=35.0, strict=True, gt=0, le=600)
    initialize_timeout: float = Field(default=300.0, strict=True, gt=0, le=3600)
    close_timeout: float = Field(default=5.0, strict=True, gt=0, le=60)
    # Replacements per method within the window; beyond it the Host fails closed.
    restart_limit: int = Field(default=2, strict=True, ge=1, le=100)
    restart_window_seconds: float = Field(default=300.0, strict=True, gt=0, le=86400)
    # Overrides for selected runner methods only, checked against the inference plan.
    methods: dict[str, InferenceMethodConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_methods(self) -> InferenceConfig:
        for method, options in self.methods.items():
            if not method or method != method.strip():
                raise ValueError("Inference method names must be nonempty and trimmed")
            if options.workers > self.max_pending:
                raise ValueError(f"{method} workers exceed max_pending")
        return self

    def workers(self, method: str) -> int:
        options = self.methods.get(method)
        return options.workers if options is not None else 1


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    turn: TurnConfig = Field(default_factory=TurnConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
