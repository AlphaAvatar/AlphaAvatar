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

import cv2
import numpy as np
from livekit import rtc

from alphaavatar.core.media import (
    PixelFormat,
    VideoFrame,
)


def from_livekit_video_frame(
    frame: rtc.VideoFrame,
) -> VideoFrame:
    rgba = frame.convert(rtc.VideoBufferType.RGBA)

    return VideoFrame(
        width=rgba.width,
        height=rgba.height,
        pixel_format=PixelFormat.RGBA,
        data=bytes(rgba.data),
        stride=rgba.width * 4,
    )


def to_livekit_video_frame(
    frame: VideoFrame,
) -> rtc.VideoFrame:
    if frame.pixel_format != PixelFormat.RGBA:
        bgr = video_frame_to_bgr(frame)
        frame = bgr_to_video_frame(bgr)

    return rtc.VideoFrame(
        frame.width,
        frame.height,
        rtc.VideoBufferType.RGBA,
        frame.packed_data(),
    )


def video_frame_to_bgr(
    frame: VideoFrame,
) -> np.ndarray:
    channels = frame.channels
    stride = int(frame.stride or frame.packed_stride)

    raw = np.frombuffer(
        frame.data,
        dtype=np.uint8,
        count=stride * frame.height,
    )

    rows = raw.reshape(
        frame.height,
        stride,
    )

    packed = rows[
        :,
        : frame.width * channels,
    ].reshape(
        frame.height,
        frame.width,
        channels,
    )

    if frame.pixel_format == PixelFormat.RGBA:
        return cv2.cvtColor(
            packed,
            cv2.COLOR_RGBA2BGR,
        )

    if frame.pixel_format == PixelFormat.RGB:
        return cv2.cvtColor(
            packed,
            cv2.COLOR_RGB2BGR,
        )

    return packed.copy()


def bgr_to_video_frame(
    bgr: np.ndarray,
) -> VideoFrame:
    rgba = cv2.cvtColor(
        bgr,
        cv2.COLOR_BGR2RGBA,
    )

    height, width, _ = rgba.shape

    return VideoFrame(
        width=width,
        height=height,
        pixel_format=PixelFormat.RGBA,
        data=rgba.tobytes(),
        stride=width * 4,
    )


def encode_video_frame_to_jpeg(
    frame: VideoFrame,
    *,
    jpeg_quality: int,
) -> bytes:
    bgr = video_frame_to_bgr(frame)

    ok, encoded = cv2.imencode(
        ".jpg",
        bgr,
        [
            int(cv2.IMWRITE_JPEG_QUALITY),
            jpeg_quality,
        ],
    )

    if not ok:
        raise RuntimeError("Failed to encode video frame to JPEG")

    return encoded.tobytes()
