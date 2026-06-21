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

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VisionInputMode(StrEnum):
    LATEST_FRAME_PER_TURN = "latest_frame_per_turn"
    SAMPLED_FRAMES_PER_TURN = "sampled_frames_per_turn"
    PERIODIC_SAMPLE = "periodic_sample"


class VisionInputConfig(BaseModel):
    """Vision input plugin and runtime mode config."""

    model_config = ConfigDict(extra="forbid")

    plugin: Literal["sampled_frame", "realtime_model"] | None = Field(
        default=None,
        description=(
            "Vision input plugin to use. sampled_frame uses LiveKit RTC video tracks; "
            "realtime_model is reserved for realtime multimodal models."
        ),
    )
    enabled: bool = Field(
        default=False,
        description="Whether to enable visual input for the agent.",
    )
    mode: VisionInputMode = Field(
        default=VisionInputMode.LATEST_FRAME_PER_TURN,
        description="How visual frames are attached to a completed user turn.",
    )


class VisionSamplingConfig(BaseModel):
    """Frame sampling policy."""

    model_config = ConfigDict(extra="forbid")

    frames_per_turn: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Maximum number of sampled visual frames attached to one completed user turn.",
    )
    frame_buffer_size: int = Field(
        default=8,
        ge=1,
        le=32,
        description="Maximum number of sampled frames to keep in memory.",
    )
    frame_sample_interval_sec: float = Field(
        default=0.5,
        ge=0.0,
        description="Minimum interval between cached video frames.",
    )


class VisionInferenceConfig(BaseModel):
    """Vision inference size config."""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(
        default=512,
        ge=64,
        le=2048,
        description="Target visual inference width passed to ImageContent.",
    )
    height: int = Field(
        default=512,
        ge=64,
        le=2048,
        description="Target visual inference height passed to ImageContent.",
    )


class VisionConfig(BaseModel):
    """Configuration for visual input used by the agent.

    This config describes the agent's visual input capability and sampling policy.
    It does not describe the user's current runtime input state, such as whether
    the user is currently using a camera, screen share, or both.
    """

    model_config = ConfigDict(extra="forbid")

    input: VisionInputConfig = Field(default_factory=VisionInputConfig)
    sampling: VisionSamplingConfig = Field(default_factory=VisionSamplingConfig)
    inference: VisionInferenceConfig = Field(default_factory=VisionInferenceConfig)

    clear_after_turn: bool = Field(
        default=True,
        description="Whether to clear cached visual frames after attaching them to a user turn.",
    )

    @model_validator(mode="after")
    def normalize(self) -> Self:
        if not self.input.enabled:
            self.input.plugin = None
            return self

        if self.input.plugin is None:
            self.input.enabled = False
            return self

        if self.input.mode == VisionInputMode.LATEST_FRAME_PER_TURN:
            self.sampling.frames_per_turn = 1

        if self.sampling.frame_buffer_size < self.sampling.frames_per_turn:
            self.sampling.frame_buffer_size = self.sampling.frames_per_turn

        return self

    @property
    def use_sampled_frame_input(self) -> bool:
        return (
            self.input.enabled
            and self.input.plugin == "sampled_frame"
            and self.input.mode
            in {
                VisionInputMode.LATEST_FRAME_PER_TURN,
                VisionInputMode.SAMPLED_FRAMES_PER_TURN,
            }
        )

    @property
    def use_latest_frame_per_turn(self) -> bool:
        return (
            self.use_sampled_frame_input
            and self.input.mode == VisionInputMode.LATEST_FRAME_PER_TURN
        )

    @property
    def use_sampled_frames_per_turn(self) -> bool:
        return (
            self.use_sampled_frame_input
            and self.input.mode == VisionInputMode.SAMPLED_FRAMES_PER_TURN
        )

    @property
    def use_realtime_video_input(self) -> bool:
        return self.input.enabled and self.input.plugin == "realtime_model"
