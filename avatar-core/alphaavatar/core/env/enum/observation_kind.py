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
from enum import StrEnum


class ObservationKind(StrEnum):
    VIDEO_FRAME = "video_frame"
    VIDEO_CLIP = "video_clip"
    SCREEN_FRAME = "screen_frame"

    AUDIO_FRAME = "audio_frame"
    AUDIO_SEGMENT = "audio_segment"
    SPEECH_FRAME = "speech_frame"
    SPEECH_SEGMENT = "speech_segment"

    TRANSCRIPT_DELTA = "transcript_delta"
    TRANSCRIPT_SEGMENT = "transcript_segment"
    TEXT_INPUT = "text_input"

    IMAGE_INPUT = "image_input"
