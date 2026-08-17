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


class PayloadView(StrEnum):
    RAW = "raw"
    ANNOTATED = "annotated"
    DERIVED = "derived"


class PayloadFormat(StrEnum):
    VIDEO_FRAME = "video.frame"
    AUDIO_FRAME = "audio.frame"

    IMAGE_URI = "image.uri"
    IMAGE_JPEG_BYTES = "image/jpeg.bytes"
    IMAGE_PNG_BYTES = "image/png.bytes"

    AUDIO_PCM16_BYTES = "audio/pcm16.bytes"
    AUDIO_WAV_BYTES = "audio/wav.bytes"

    TEXT = "text.plain"
