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

from collections.abc import Iterable
from dataclasses import replace

from alphaavatar.agents.router.enums import AddressingEvidenceKind, AddressingMode, AssessmentLabel
from alphaavatar.agents.router.schemas import (
    InteractionAddressingEvidence,
    InteractionEntityRef,
    TurnTakingAssessment,
)

from .schemas.state import AddressingEvidenceRecord

_EntityKey = tuple[str, str, int, str, str]
_TargetKey = tuple[str, str, tuple[_EntityKey, ...]]


def _entity_key(entity: InteractionEntityRef) -> _EntityKey:
    perception = entity.entity
    return (
        entity.kind.value,
        entity.source.source_id if entity.source else "",
        entity.source.source_generation if entity.source else 0,
        perception.entity_id if perception else "",
        "" if perception else entity.device_id or "",
    )


def _target_key(evidence: InteractionAddressingEvidence) -> _TargetKey:
    return (
        evidence.label.value,
        evidence.addressing_mode.value,
        tuple(sorted(_entity_key(entity) for entity in evidence.addressees)),
    )


class AddressingFusion:
    """Fuse addressees only: an evidence record's speaker never identifies the whole input."""

    def __init__(self, *, conflict_margin: float = 0.1) -> None:
        if not 0.0 <= conflict_margin <= 1.0:
            raise ValueError("conflict_margin must be between 0 and 1")
        self._conflict_margin = conflict_margin

    @staticmethod
    def same_target(
        left: InteractionAddressingEvidence | None, right: InteractionAddressingEvidence | None
    ) -> bool:
        if left is None or right is None:
            return left is right
        return _target_key(left) == _target_key(right)

    def resolve(
        self, records: Iterable[AddressingEvidenceRecord]
    ) -> InteractionAddressingEvidence | None:
        # A new UNKNOWN replaces an older conclusion from that producer; it does not
        # erase the observation. Visual orientation remains a different proposition.
        latest = {}
        for record in records:
            kind = record.evidence.evidence_kind
            source = (
                record.evidence.speaker.source
                if kind == AddressingEvidenceKind.VISUAL_ORIENTATION
                else None
            )
            key = record.source, kind, source
            previous = latest.get(key)
            at = record.target_time_range.end.monotonic_ns if record.target_time_range else 0
            before = (
                previous.target_time_range.end.monotonic_ns
                if previous and previous.target_time_range
                else 0
            )
            if previous is None or (at, record.sequence) > (before, previous.sequence):
                latest[key] = record

        current = tuple(latest.values())
        explicit = [
            r for r in current if r.evidence.evidence_kind == AddressingEvidenceKind.EXPLICIT
        ]
        semantic = [
            r for r in current if r.evidence.evidence_kind == AddressingEvidenceKind.SEMANTIC
        ]
        visual = [
            r
            for r in current
            if r.evidence.evidence_kind == AddressingEvidenceKind.VISUAL_ORIENTATION
        ]
        focus = [
            r
            for r in current
            if r.evidence.evidence_kind == AddressingEvidenceKind.CONVERSATION_FOCUS
        ]
        candidates = [r for r in explicit if not r.evidence.abstains]
        if not candidates:
            candidates = [r for r in semantic if not r.evidence.abstains]
        if not candidates:
            candidates = [r for r in visual if r.evidence.label == AssessmentLabel.POSITIVE]
        if not candidates and not semantic and not visual:
            candidates = [r for r in focus if not r.evidence.abstains]

        if not candidates:
            return None

        candidates.sort(
            key=lambda record: (record.evidence.confidence, record.sequence), reverse=True
        )

        best = candidates[0]
        best_key = _target_key(best.evidence)

        if any(
            _target_key(record.evidence) != best_key
            and record.evidence.confidence >= best.evidence.confidence - self._conflict_margin
            for record in candidates[1:]
        ):
            return None

        supporting = sorted(
            (record for record in candidates if _target_key(record.evidence) == best_key),
            key=lambda record: record.sequence,
        )

        return replace(
            best.evidence,
            evidence_observation_ids=tuple(
                dict.fromkeys(
                    observation_id
                    for record in supporting
                    for observation_id in record.evidence.evidence_observation_ids
                )
            ),
        )

    def apply(
        self, *, assessment: TurnTakingAssessment, records: Iterable[AddressingEvidenceRecord]
    ) -> TurnTakingAssessment:
        evidence = self.resolve(records)
        if evidence is None:
            return replace(
                assessment,
                addressees=(),
                addressing=AssessmentLabel.UNKNOWN,
                addressing_mode=AddressingMode.UNKNOWN,
                addressing_confidence=None,
                addressing_evidence_observation_ids=(),
            )

        return replace(
            assessment,
            addressees=evidence.addressees,
            addressing=evidence.label,
            addressing_mode=evidence.addressing_mode,
            addressing_confidence=evidence.confidence,
            addressing_evidence_observation_ids=evidence.evidence_observation_ids,
        )
