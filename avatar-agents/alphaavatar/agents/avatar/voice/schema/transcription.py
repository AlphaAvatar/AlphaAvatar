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


class TranscriptionEventType(StrEnum):
    INTERIM_TRANSCRIPT = "interim_transcript"
    FINAL_TRANSCRIPT = "final_transcript"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class TranscriptionEvent:
    type: TranscriptionEventType
    source_id: str
    segment_id: str
    text: str = ""

    language: str | None = None
    confidence: float | None = None

    start_time: float | None = None
    end_time: float | None = None

    provider: str | None = None
    model: str | None = None
    reason: str | None = None
