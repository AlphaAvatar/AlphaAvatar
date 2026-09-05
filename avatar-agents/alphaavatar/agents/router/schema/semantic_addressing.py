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

import math
from dataclasses import dataclass
from typing import Any

from ..enum import SemanticAddressingLabel


@dataclass(frozen=True, slots=True)
class SemanticAddressingTranscript:
    text: str
    final: bool = True

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Semantic addressing transcript cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "final": self.final}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SemanticAddressingTranscript:
        return cls(text=str(data["text"]), final=bool(data.get("final", True)))


@dataclass(frozen=True, slots=True)
class SemanticAddressingRequest:
    avatar_identities: tuple[str, ...] = ()
    previous_focus: str | None = None
    transcript_segments: tuple[SemanticAddressingTranscript, ...] = ()

    def __post_init__(self) -> None:
        if any(not identity.strip() for identity in self.avatar_identities):
            raise ValueError("Avatar identities cannot contain empty values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "avatar_identities": list(self.avatar_identities),
            "previous_focus": self.previous_focus,
            "transcript_segments": [segment.to_dict() for segment in self.transcript_segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SemanticAddressingRequest:
        return cls(
            avatar_identities=tuple(str(value) for value in data.get("avatar_identities", ())),
            previous_focus=data.get("previous_focus"),
            transcript_segments=tuple(
                SemanticAddressingTranscript.from_dict(segment)
                for segment in data.get("transcript_segments", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class SemanticAddressingResult:
    label: SemanticAddressingLabel
    label_0_logit: float
    label_1_logit: float
    p_avatar: float

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(value)
            for value in (self.label_0_logit, self.label_1_logit, self.p_avatar)
        ):
            raise ValueError("Semantic addressing result must contain finite values")
        if not 0.0 <= self.p_avatar <= 1.0:
            raise ValueError("p_avatar must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label.value,
            "label_0_logit": self.label_0_logit,
            "label_1_logit": self.label_1_logit,
            "p_avatar": self.p_avatar,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SemanticAddressingResult:
        return cls(
            label=SemanticAddressingLabel(data["label"]),
            label_0_logit=float(data["label_0_logit"]),
            label_1_logit=float(data["label_1_logit"]),
            p_avatar=float(data["p_avatar"]),
        )
