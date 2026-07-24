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


class VoiceActivityEventType(StrEnum):
    INFERENCE_DONE = "inference_done"
    START_OF_SPEECH = "start_of_speech"
    END_OF_SPEECH = "end_of_speech"


@dataclass(slots=True, frozen=True)
class VoiceActivityEvent:
    """
    AlphaAvatar-owned voice activity event.

    samples_index:
        End position of the processed window in the original input sample-rate
        domain, not the Silero model sample-rate domain.

    timestamp:
        Stream-relative time derived from samples_index / input_sample_rate.
    """

    type: VoiceActivityEventType
    samples_index: int
    timestamp: float
    input_sample_rate: int
    speaking: bool

    probability: float | None = None
    window_samples: int = 0
    speech_duration: float = 0.0
    silence_duration: float = 0.0
    inference_duration: float = 0.0
    raw_accumulated_speech: float = 0.0
    raw_accumulated_silence: float = 0.0
    reason: str | None = None
