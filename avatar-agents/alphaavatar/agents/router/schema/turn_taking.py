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

from alphaavatar.core.env import (
    AnnotationKind,
    EnvAnnotation,
    PerceptionEntityRef,
    PerceptionSegmentRef,
)
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange

from ..enum import (
    AddressingEvidenceKind,
    AddressingMode,
    InteractionEntityKind,
    TurnTakingAction,
    TurnTakingMode,
)


def _validate_candidate(
    turn_candidate_id: str,
    candidate_revision: int,
    confidence: float,
) -> None:
    if not turn_candidate_id:
        raise ValueError("turn_candidate_id cannot be empty")
    if candidate_revision <= 0:
        raise ValueError("candidate_revision must be positive")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")


def _annotation(
    *,
    kind: AnnotationKind,
    source: str,
    data: dict[str, Any],
    observation_id: str | None,
    frame_id: str | None,
) -> EnvAnnotation:
    if (observation_id is None) == (frame_id is None):
        raise ValueError("Exactly one annotation target is required")

    return EnvAnnotation(
        source=source,
        kind=kind,
        observation_id=observation_id,
        frame_id=frame_id,
        data=data,
    )


@dataclass(frozen=True, slots=True)
class InteractionEntityRef:
    kind: InteractionEntityKind
    entity: PerceptionEntityRef | None = None
    transport_participant_id: str | None = None

    def __post_init__(self) -> None:
        if self.transport_participant_id == "":
            raise ValueError("transport_participant_id cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind.value}

        if self.entity is not None:
            data["entity"] = self.entity.to_dict()

        if self.transport_participant_id is not None:
            data["transport_participant_id"] = self.transport_participant_id

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InteractionEntityRef:
        entity = data.get("entity")
        return cls(
            kind=InteractionEntityKind(data["kind"]),
            entity=PerceptionEntityRef.from_dict(entity) if entity else None,
            transport_participant_id=data.get("transport_participant_id"),
        )


@dataclass(frozen=True, slots=True)
class InteractionAddressingEvidence:
    evidence_kind: AddressingEvidenceKind

    speaker: InteractionEntityRef
    addressees: tuple[InteractionEntityRef, ...]
    addressing_mode: AddressingMode
    confidence: float

    evidence_label: str | None = None
    raw_score: float | None = None
    evidence_observation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

        if self.raw_score is not None and not 0.0 <= self.raw_score <= 1.0:
            raise ValueError("raw_score must be between 0 and 1")

        if (
            self.addressing_mode
            in {
                AddressingMode.DIRECT,
                AddressingMode.GROUP,
            }
            and not self.addressees
        ):
            raise ValueError(f"{self.addressing_mode.value} addressing requires addressees")

    @property
    def abstains(self) -> bool:
        return self.addressing_mode == AddressingMode.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "evidence_kind": self.evidence_kind.value,
            "speaker": self.speaker.to_dict(),
            "addressees": [addressee.to_dict() for addressee in self.addressees],
            "addressing_mode": self.addressing_mode.value,
            "confidence": self.confidence,
            "evidence_observation_ids": list(self.evidence_observation_ids),
        }

        if self.evidence_label is not None:
            data["evidence_label"] = self.evidence_label

        if self.raw_score is not None:
            data["raw_score"] = self.raw_score

        return data

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> InteractionAddressingEvidence:
        return cls(
            evidence_kind=AddressingEvidenceKind(data["evidence_kind"]),
            speaker=InteractionEntityRef.from_dict(data["speaker"]),
            addressees=tuple(
                InteractionEntityRef.from_dict(addressee)
                for addressee in data.get("addressees", ())
            ),
            addressing_mode=AddressingMode(data["addressing_mode"]),
            confidence=float(data["confidence"]),
            evidence_label=data.get("evidence_label"),
            raw_score=(float(data["raw_score"]) if data.get("raw_score") is not None else None),
            evidence_observation_ids=tuple(data.get("evidence_observation_ids", ())),
        )

    @classmethod
    def from_annotation(
        cls,
        annotation: EnvAnnotation,
    ) -> InteractionAddressingEvidence:
        if annotation.kind != AnnotationKind.INTERACTION_ADDRESSING_EVIDENCE:
            raise ValueError(
                f"Expected "
                f"{AnnotationKind.INTERACTION_ADDRESSING_EVIDENCE.value}, "
                f"got {annotation.kind.value}"
            )

        return cls.from_dict(annotation.data)

    def to_annotation(
        self,
        *,
        source: str,
        observation_id: str,
    ) -> EnvAnnotation:
        if not observation_id:
            raise ValueError("observation_id cannot be empty")

        return EnvAnnotation(
            source=source,
            kind=AnnotationKind.INTERACTION_ADDRESSING_EVIDENCE,
            observation_id=observation_id,
            data=self.to_dict(),
        )


@dataclass(frozen=True, slots=True)
class InteractionAddressing:
    turn_candidate_id: str
    candidate_revision: int
    speaker: InteractionEntityRef
    addressees: tuple[InteractionEntityRef, ...]
    addressing_mode: AddressingMode
    confidence: float
    evidence_observation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_candidate(
            self.turn_candidate_id,
            self.candidate_revision,
            self.confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_candidate_id": self.turn_candidate_id,
            "candidate_revision": self.candidate_revision,
            "speaker": self.speaker.to_dict(),
            "addressees": [entity.to_dict() for entity in self.addressees],
            "addressing_mode": self.addressing_mode.value,
            "confidence": self.confidence,
            "evidence_observation_ids": list(self.evidence_observation_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InteractionAddressing:
        return cls(
            turn_candidate_id=data["turn_candidate_id"],
            candidate_revision=int(data["candidate_revision"]),
            speaker=InteractionEntityRef.from_dict(data["speaker"]),
            addressees=tuple(
                InteractionEntityRef.from_dict(entity) for entity in data.get("addressees", ())
            ),
            addressing_mode=AddressingMode(data["addressing_mode"]),
            confidence=float(data["confidence"]),
            evidence_observation_ids=tuple(data.get("evidence_observation_ids", ())),
        )

    @classmethod
    def from_annotation(cls, annotation: EnvAnnotation) -> InteractionAddressing:
        if annotation.kind != AnnotationKind.INTERACTION_ADDRESSING:
            raise ValueError(
                f"Expected {AnnotationKind.INTERACTION_ADDRESSING.value}, "
                f"got {annotation.kind.value}"
            )
        return cls.from_dict(annotation.data)

    def to_annotation(
        self,
        *,
        source: str,
        observation_id: str | None = None,
        frame_id: str | None = None,
    ) -> EnvAnnotation:
        return _annotation(
            kind=AnnotationKind.INTERACTION_ADDRESSING,
            source=source,
            data=self.to_dict(),
            observation_id=observation_id,
            frame_id=frame_id,
        )


@dataclass(frozen=True, slots=True)
class TurnTakingDecision:
    turn_candidate_id: str
    candidate_revision: int
    turn_mode: TurnTakingMode
    action: TurnTakingAction
    confidence: float

    actor: InteractionEntityRef | None = None
    addressees: tuple[InteractionEntityRef, ...] = ()
    input_observation_ids: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_candidate(
            self.turn_candidate_id,
            self.candidate_revision,
            self.confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "turn_candidate_id": self.turn_candidate_id,
            "candidate_revision": self.candidate_revision,
            "turn_mode": self.turn_mode.value,
            "action": self.action.value,
            "confidence": self.confidence,
            "addressees": [entity.to_dict() for entity in self.addressees],
            "input_observation_ids": list(self.input_observation_ids),
        }

        if self.actor is not None:
            data["actor"] = self.actor.to_dict()

        if self.reason is not None:
            data["reason"] = self.reason

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TurnTakingDecision:
        actor = data.get("actor")
        return cls(
            turn_candidate_id=data["turn_candidate_id"],
            candidate_revision=int(data["candidate_revision"]),
            turn_mode=TurnTakingMode(data["turn_mode"]),
            action=TurnTakingAction(data["action"]),
            confidence=float(data["confidence"]),
            actor=InteractionEntityRef.from_dict(actor) if actor else None,
            addressees=tuple(
                InteractionEntityRef.from_dict(entity) for entity in data.get("addressees", ())
            ),
            input_observation_ids=tuple(data.get("input_observation_ids", ())),
            reason=data.get("reason"),
        )

    @classmethod
    def from_annotation(cls, annotation: EnvAnnotation) -> TurnTakingDecision:
        if annotation.kind != AnnotationKind.INTERACTION_TURN:
            raise ValueError(
                f"Expected {AnnotationKind.INTERACTION_TURN.value}, got {annotation.kind.value}"
            )
        return cls.from_dict(annotation.data)

    def to_annotation(
        self,
        *,
        source: str,
        observation_id: str | None = None,
        frame_id: str | None = None,
    ) -> EnvAnnotation:
        return _annotation(
            kind=AnnotationKind.INTERACTION_TURN,
            source=source,
            data=self.to_dict(),
            observation_id=observation_id,
            frame_id=frame_id,
        )


@dataclass(frozen=True, slots=True)
class TurnTakingAudioEvidence:
    segment: PerceptionSegmentRef
    time_range: RuntimeTimeRange

    pcm16_bytes: bytes
    sample_rate: int
    num_channels: int
    samples_per_channel: int

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.num_channels <= 0:
            raise ValueError("num_channels must be positive")
        if self.samples_per_channel <= 0:
            raise ValueError("samples_per_channel must be positive")

        expected_size = self.samples_per_channel * self.num_channels * 2
        if len(self.pcm16_bytes) != expected_size:
            raise ValueError(
                "PCM size does not match declared audio shape: "
                f"bytes={len(self.pcm16_bytes)}, expected={expected_size}"
            )


@dataclass(frozen=True, slots=True)
class TurnTakingEvidence:
    turn_candidate_id: str
    candidate_revision: int
    turn_mode: TurnTakingMode

    speaker: InteractionEntityRef
    started_at: RuntimeTime
    updated_at: RuntimeTime

    segments: tuple[PerceptionSegmentRef, ...]
    input_observation_ids: tuple[str, ...]

    transcript: str | None = None
    audio: tuple[TurnTakingAudioEvidence, ...] = ()

    speech_active: bool = False
    has_perception_gap: bool = False

    def __post_init__(self) -> None:
        if not self.turn_candidate_id:
            raise ValueError("turn_candidate_id cannot be empty")
        if self.candidate_revision <= 0:
            raise ValueError("candidate_revision must be positive")


@dataclass(frozen=True, slots=True)
class TurnTakingAssessment:
    turn_candidate_id: str
    candidate_revision: int
    turn_mode: TurnTakingMode

    confidence: float
    addressing_confidence: float | None = None

    end_of_turn_probability: float | None = None
    interruption_probability: float | None = None
    proactive_probability: float | None = None

    addressees: tuple[InteractionEntityRef, ...] = ()
    addressing_mode: AddressingMode = AddressingMode.UNKNOWN
    addressing_evidence_observation_ids: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.turn_candidate_id:
            raise ValueError("turn_candidate_id cannot be empty")
        if self.candidate_revision <= 0:
            raise ValueError("candidate_revision must be positive")

        for name, value in (
            ("confidence", self.confidence),
            ("addressing_confidence", self.addressing_confidence),
            ("end_of_turn_probability", self.end_of_turn_probability),
            ("interruption_probability", self.interruption_probability),
            ("proactive_probability", self.proactive_probability),
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
