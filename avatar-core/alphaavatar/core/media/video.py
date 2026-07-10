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

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .formats import PayloadFormat, PayloadView
from .payload import MediaPayload


class PixelFormat(StrEnum):
    RGBA = "rgba"
    RGB = "rgb"
    BGR = "bgr"


_PIXEL_CHANNELS: dict[PixelFormat, int] = {
    PixelFormat.RGBA: 4,
    PixelFormat.RGB: 3,
    PixelFormat.BGR: 3,
}


@dataclass(slots=True, frozen=True)
class VideoFrame:
    """
    AlphaAvatar-owned generic video frame.

    This type must remain independent from LiveKit, aiortc, Agora, or any
    other transport implementation.
    """

    width: int
    height: int
    pixel_format: PixelFormat
    data: bytes
    stride: int | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Invalid video frame size: width={self.width}, height={self.height}")

        channels = _PIXEL_CHANNELS[self.pixel_format]
        packed_stride = self.width * channels
        stride = self.stride or packed_stride

        if stride < packed_stride:
            raise ValueError(
                f"Video frame stride is too small: stride={stride}, minimum={packed_stride}"
            )

        required_size = stride * self.height
        if len(self.data) < required_size:
            raise ValueError(
                f"Video frame data is too short: bytes={len(self.data)}, required={required_size}"
            )

        object.__setattr__(self, "stride", stride)

    @property
    def channels(self) -> int:
        return _PIXEL_CHANNELS[self.pixel_format]

    @property
    def packed_stride(self) -> int:
        return self.width * self.channels

    @property
    def is_packed(self) -> bool:
        return self.stride == self.packed_stride

    def packed_data(self) -> bytes:
        if self.is_packed:
            required = self.packed_stride * self.height
            return self.data[:required]

        rows: list[bytes] = []
        stride = int(self.stride or self.packed_stride)

        for row_index in range(self.height):
            start = row_index * stride
            end = start + self.packed_stride
            rows.append(self.data[start:end])

        return b"".join(rows)


class VideoFramePayload(MediaPayload):
    def __init__(
        self,
        *,
        frame_id: str | None,
        width: int,
        height: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            modality="video_frame",
            metadata=metadata,
        )

        self.frame_id = frame_id
        self.width = width
        self.height = height

    @classmethod
    def create(
        cls,
        *,
        frame: VideoFrame,
        frame_id: str | None,
        jpeg_bytes: bytes | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VideoFramePayload:
        payload = cls(
            frame_id=frame_id,
            width=frame.width,
            height=frame.height,
            metadata=metadata,
        )

        payload.put(
            PayloadFormat.VIDEO_FRAME,
            frame,
            view=PayloadView.RAW,
        )

        if jpeg_bytes is not None:
            payload.put(
                PayloadFormat.IMAGE_JPEG_BYTES,
                jpeg_bytes,
                view=PayloadView.RAW,
            )

        return payload
