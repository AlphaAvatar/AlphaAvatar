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

from pydantic import BaseModel


class UserInputModality(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    VIDEO = "video"
    SCREEN_SHARE = "screen_share"


class ActiveVisualSource(StrEnum):
    NONE = "none"
    CAMERA = "camera"
    SCREEN_SHARE = "screen_share"
    BOTH = "both"


class UserInputState(BaseModel):
    has_text_input: bool = False
    has_voice_input: bool = False
    has_camera_video: bool = False
    has_screen_share: bool = False

    active_visual_source: ActiveVisualSource = ActiveVisualSource.NONE

    active_camera_track_sid: str | None = None
    active_screen_share_track_sid: str | None = None

    last_text_ts: float | None = None
    last_voice_ts: float | None = None
    last_camera_frame_ts: float | None = None
    last_screen_share_frame_ts: float | None = None

    def update_visual_source(self) -> None:
        if self.has_camera_video and self.has_screen_share:
            self.active_visual_source = ActiveVisualSource.BOTH
        elif self.has_screen_share:
            self.active_visual_source = ActiveVisualSource.SCREEN_SHARE
        elif self.has_camera_video:
            self.active_visual_source = ActiveVisualSource.CAMERA
        else:
            self.active_visual_source = ActiveVisualSource.NONE
