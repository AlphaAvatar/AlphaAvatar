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

from livekit import rtc

from alphaavatar.core.media import PixelFormat, VideoFrame
from alphaavatar.core.media.codecs.video import bgr_to_video_frame, video_frame_to_bgr


def from_livekit_video_frame(frame: rtc.VideoFrame) -> VideoFrame:
    rgba = frame.convert(rtc.VideoBufferType.RGBA)
    return VideoFrame(
        width=rgba.width,
        height=rgba.height,
        pixel_format=PixelFormat.RGBA,
        data=bytes(rgba.data),
        stride=rgba.width * 4,
    )


def to_livekit_video_frame(frame: VideoFrame) -> rtc.VideoFrame:
    if frame.pixel_format != PixelFormat.RGBA:
        bgr = video_frame_to_bgr(frame)
        frame = bgr_to_video_frame(bgr)
    return rtc.VideoFrame(
        frame.width,
        frame.height,
        rtc.VideoBufferType.RGBA,
        frame.packed_data(),
    )
