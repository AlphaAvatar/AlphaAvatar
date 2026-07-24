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
    """
    Logical representation view.

    RAW:
        Original input representation produced by an input adapter.

    ANNOTATED:
        Representation containing perception annotations, such as face boxes.

    DERIVED:
        Other derived representations, such as thumbnails or provider-ready blocks.
    """

    RAW = "raw"
    ANNOTATED = "annotated"
    DERIVED = "derived"


class PayloadFormat(StrEnum):
    """
    AlphaAvatar-owned payload formats.

    Do not add provider-specific or RTC-specific classes here.
    """

    # Generic video frame owned by AlphaAvatar.
    VIDEO_FRAME = "video.frame"

    # Generic audio frame owned by AlphaAvatar.
    AUDIO_FRAME = "audio.frame"

    # Encoded visual representations.
    IMAGE_JPEG_BYTES = "image/jpeg.bytes"
    IMAGE_PNG_BYTES = "image/png.bytes"

    # Audio representations.
    AUDIO_PCM16_BYTES = "audio/pcm16.bytes"
    AUDIO_WAV_BYTES = "audio/wav.bytes"

    # Reserved for provider adapters.
    PROVIDER_CONTENT_BLOCK = "provider.content_block"
