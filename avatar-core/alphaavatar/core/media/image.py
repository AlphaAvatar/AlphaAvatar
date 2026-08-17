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

from typing import Any

from .enum.formats import PayloadFormat, PayloadView
from .payload import MediaPayload
from .video import VideoFrame


class ImagePayload(MediaPayload):
    def __init__(
        self,
        *,
        image_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(modality="image", metadata=metadata)
        self.image_id = image_id

    @classmethod
    def create(
        cls,
        *,
        image_id: str | None = None,
        frame: VideoFrame | None = None,
        uri: str | None = None,
        jpeg_bytes: bytes | None = None,
        png_bytes: bytes | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ImagePayload:
        if frame is None and uri is None and jpeg_bytes is None and png_bytes is None:
            raise ValueError("Image payload requires a frame, URI, or encoded image")

        payload = cls(image_id=image_id, metadata=metadata)
        if frame is not None:
            payload.put(PayloadFormat.VIDEO_FRAME, frame, view=PayloadView.RAW)
        if uri is not None:
            payload.put(PayloadFormat.IMAGE_URI, uri, view=PayloadView.RAW)
        if jpeg_bytes is not None:
            payload.put(PayloadFormat.IMAGE_JPEG_BYTES, jpeg_bytes, view=PayloadView.RAW)
        if png_bytes is not None:
            payload.put(PayloadFormat.IMAGE_PNG_BYTES, png_bytes, view=PayloadView.RAW)
        return payload
