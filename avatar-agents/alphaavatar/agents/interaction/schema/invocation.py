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
from typing import Any

from alphaavatar.core.env import PerceptionSegmentRef


@dataclass(frozen=True, slots=True)
class InvocationPhrase:
    phrase_id: str
    text: str
    boosting_score: float = 1.0
    trigger_threshold: float = 0.25

    def __post_init__(self) -> None:
        if not self.phrase_id:
            raise ValueError("phrase_id cannot be empty")
        if any(character.isspace() or character in {"/", "@"} for character in self.phrase_id):
            raise ValueError("phrase_id cannot contain whitespace, '/' or '@'")
        if not self.text.strip():
            raise ValueError("Invocation phrase text cannot be empty")
        if self.boosting_score <= 0:
            raise ValueError("boosting_score must be positive")
        if not 0.0 <= self.trigger_threshold <= 1.0:
            raise ValueError("trigger_threshold must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "phrase_id": self.phrase_id,
            "text": self.text,
            "boosting_score": self.boosting_score,
            "trigger_threshold": self.trigger_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvocationPhrase:
        return cls(
            phrase_id=str(data["phrase_id"]),
            text=str(data["text"]),
            boosting_score=float(data.get("boosting_score", 1.0)),
            trigger_threshold=float(data.get("trigger_threshold", 0.25)),
        )


@dataclass(frozen=True, slots=True)
class InvocationDetection:
    segment: PerceptionSegmentRef
    observation_id: str

    phrase_id: str
    phrase: str
    stream_offset_sec: float

    raw_score: float | None = None

    def __post_init__(self) -> None:
        if not self.observation_id:
            raise ValueError("observation_id cannot be empty")
        if not self.phrase_id:
            raise ValueError("phrase_id cannot be empty")
        if not self.phrase:
            raise ValueError("phrase cannot be empty")
        if self.stream_offset_sec < 0:
            raise ValueError("stream_offset_sec cannot be negative")
        if self.raw_score is not None and not 0.0 <= self.raw_score <= 1.0:
            raise ValueError("raw_score must be between 0 and 1")
