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


class SpeechCancellationReason(StrEnum):
    INPUT_GAP = "input_gap"
    SOURCE_REPLACED = "source_replaced"
    SOURCE_ENDED = "source_ended"
    SOURCE_ERROR = "source_error"
    SOURCE_MUTED = "source_muted"
    SOURCE_GENERATION_RETIRED = "source_generation_retired"
    VAD_INPUT_REJECTED = "vad_input_rejected"
    VAD_ERROR = "vad_error"
    VAD_ENDED = "vad_ended"
    EMPTY_SEGMENT = "empty_segment"
    CLOSE_TIMEOUT = "close_timeout"
    SOURCE_CLOSED = "source_closed"
    SHUTDOWN = "shutdown"
    PROCESSING_ERROR = "processing_error"
