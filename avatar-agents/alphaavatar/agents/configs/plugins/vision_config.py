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
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VisionInputMode(StrEnum):
    LATEST_FRAME_PER_TURN = "latest_frame_per_turn"
    SAMPLED_FRAMES_PER_TURN = "sampled_frames_per_turn"
    PERIODIC_SAMPLE = "periodic_sample"


class VisionConfig(BaseModel):
    """Configuration for visual input used by the agent.

    This config describes the agent's visual input capability and sampling policy.
    It does not describe the user's current runtime input state, such as whether
    the user is currently using a camera, screen share, or both.
    """

    vision_input_plugin: Literal["sampled_frame", "realtime_model"] | None = Field(
        default=None,
        description="Vision input plugin to use. sampled_frame uses LiveKit RTC video tracks; realtime_model is reserved for realtime multimodal models.",
    )
    vision_input_enabled: bool = Field(
        default=False,
        description="Whether to enable visual input for the agent.",
    )
    vision_input_mode: VisionInputMode = Field(
        default=VisionInputMode.LATEST_FRAME_PER_TURN,
        description="How visual frames are attached to a completed user turn.",
    )

    vision_frames_per_turn: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Maximum number of sampled visual frames attached to one completed user turn.",
    )
    vision_frame_buffer_size: int = Field(
        default=8,
        ge=1,
        le=32,
        description="Maximum number of sampled frames to keep in memory.",
    )
    vision_frame_sample_interval_sec: float = Field(
        default=0.5,
        ge=0.0,
        description="Minimum interval between cached video frames.",
    )

    vision_inference_width: int = Field(
        default=512,
        ge=64,
        le=2048,
        description="Target visual inference width passed to ImageContent.",
    )
    vision_inference_height: int = Field(
        default=512,
        ge=64,
        le=2048,
        description="Target visual inference height passed to ImageContent.",
    )

    vision_clear_after_turn: bool = Field(
        default=True,
        description="Whether to clear cached visual frames after attaching them to a user turn.",
    )

    @model_validator(mode="after")
    def normalize(self) -> VisionConfig:
        if not self.vision_input_enabled:
            self.vision_input_plugin = None
            return self

        if self.vision_input_plugin is None:
            self.vision_input_enabled = False
            return self

        if self.vision_input_mode == VisionInputMode.LATEST_FRAME_PER_TURN:
            self.vision_frames_per_turn = 1

        if self.vision_frame_buffer_size < self.vision_frames_per_turn:
            self.vision_frame_buffer_size = self.vision_frames_per_turn

        return self

    @property
    def use_sampled_frame_input(self) -> bool:
        return (
            self.vision_input_enabled
            and self.vision_input_plugin == "sampled_frame"
            and self.vision_input_mode
            in {
                VisionInputMode.LATEST_FRAME_PER_TURN,
                VisionInputMode.SAMPLED_FRAMES_PER_TURN,
            }
        )

    @property
    def use_latest_frame_per_turn(self) -> bool:
        return (
            self.use_sampled_frame_input
            and self.vision_input_mode == VisionInputMode.LATEST_FRAME_PER_TURN
        )

    @property
    def use_sampled_frames_per_turn(self) -> bool:
        return (
            self.use_sampled_frame_input
            and self.vision_input_mode == VisionInputMode.SAMPLED_FRAMES_PER_TURN
        )

    @property
    def use_realtime_video_input(self) -> bool:
        return self.vision_input_enabled and self.vision_input_plugin == "realtime_model"
