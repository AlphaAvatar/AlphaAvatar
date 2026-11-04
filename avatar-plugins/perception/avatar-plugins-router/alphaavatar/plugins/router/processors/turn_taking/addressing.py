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

import logging
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import replace
from typing import TypeVar

from alphaavatar.agents.router.schemas import (
    InteractionAddressingEvidence,
    InteractionEntityRef,
    TurnTakingAssessment,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import AnnotationKind
from alphaavatar.core.env.schemas import PerceptionSegmentRef, PerceptionSourceRef
from alphaavatar.core.perception.schemas import PerceptionEvent

from .fusion import AddressingFusion
from .schemas.state import AddressingEvidenceRecord, SpeakerKey, TurnCandidate

logger = logging.getLogger(__name__)
_Key = TypeVar("_Key", bound=Hashable)


class TurnAddressing:
    """Correlate and fuse addressing evidence without owning candidate lifetimes."""

    _MAX_ORPHANS = 64
    _MAX_ADDRESSING_RECORDS_PER_TARGET = 8

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        fusion: AddressingFusion,
        alignment_sec: float,
        required_sources: tuple[str, ...],
    ) -> None:
        self._runtime = runtime
        self._fusion = fusion
        self._unsegmented_alignment_ns = int(alignment_sec * 1_000_000_000)
        self._required_addressing_sources = frozenset(required_sources)
        self._by_observation: dict[str, list[AddressingEvidenceRecord]] = {}
        self._by_segment: dict[PerceptionSegmentRef, list[AddressingEvidenceRecord]] = {}
        self._unsegmented: dict[str, AddressingEvidenceRecord] = {}

    @classmethod
    def _store_addressing(
        cls,
        mapping: dict[_Key, list[AddressingEvidenceRecord]],
        key: _Key,
        record: AddressingEvidenceRecord,
    ) -> None:
        if key not in mapping and len(mapping) >= cls._MAX_ORPHANS:
            mapping.pop(next(iter(mapping)))

        records = mapping.setdefault(key, [])
        if any(current.annotation_id == record.annotation_id for current in records):
            return

        records.append(record)
        if len(records) > cls._MAX_ADDRESSING_RECORDS_PER_TARGET:
            del records[: -cls._MAX_ADDRESSING_RECORDS_PER_TARGET]

    def receive(self, event: PerceptionEvent) -> AddressingEvidenceRecord | None:
        annotation = event.annotation
        if annotation is None or annotation.kind != AnnotationKind.INTERACTION_ADDRESSING_EVIDENCE:
            return None

        observation_id = annotation.observation_id
        if observation_id is None:
            logger.warning(
                "Addressing evidence has no observation target annotation_id=%s",
                annotation.annotation_id,
            )
            return None

        record = AddressingEvidenceRecord(
            annotation_id=annotation.annotation_id,
            source=annotation.source,
            sequence=event.sequence,
            target_observation_id=observation_id,
            published_at=event.time_range.end,
            evidence=InteractionAddressingEvidence.from_annotation(annotation),
        )
        observation = self._runtime.perception.timeline.get_observation(
            observation_id=observation_id
        )

        if observation is None:
            self._store_addressing(self._by_observation, observation_id, record)
            return None

        return self._with_target(record, observation)

    @staticmethod
    def _with_target(
        record: AddressingEvidenceRecord, observation: EnvObservation
    ) -> AddressingEvidenceRecord:
        return replace(
            record, target_time_range=observation.time_range, target_segment=observation.segment
        )

    def take_observation(self, observation: EnvObservation) -> tuple[AddressingEvidenceRecord, ...]:
        if records := self._by_observation.pop(observation.observation_id, None):
            return tuple(self._with_target(record, observation) for record in records)
        return ()

    def defer_segment(
        self, segment: PerceptionSegmentRef, record: AddressingEvidenceRecord
    ) -> None:
        self._store_addressing(self._by_segment, segment, record)

    def take_segment(self, segment: PerceptionSegmentRef) -> Sequence[AddressingEvidenceRecord]:
        return self._by_segment.pop(segment, ())

    def deferred_segments(self, source: PerceptionSourceRef) -> tuple[PerceptionSegmentRef, ...]:
        return tuple(segment for segment in self._by_segment if segment.source == source)

    def defer_unsegmented(self, record: AddressingEvidenceRecord) -> None:
        if (
            record.annotation_id not in self._unsegmented
            and len(self._unsegmented) >= self._MAX_ORPHANS
        ):
            self._unsegmented.pop(next(iter(self._unsegmented)))

        self._unsegmented[record.annotation_id] = record

    def take_unsegmented(self) -> tuple[AddressingEvidenceRecord, ...]:
        records = tuple(self._unsegmented.values())
        self._unsegmented.clear()
        return records

    def clear(self) -> None:
        self._by_observation.clear()
        self._by_segment.clear()
        self._unsegmented.clear()

    def same_subject(self, left: InteractionEntityRef, right: InteractionEntityRef) -> bool:
        if (
            left.entity is None
            or right.entity is None
            or left.source is None
            or right.source is None
        ):
            return False

        if not all(
            self._runtime.participants.source_is_current(source)
            for source in (left.source, right.source)
        ):
            return False

        if left.source == right.source and left.entity.entity_id == right.entity.entity_id:
            return True

        first = self._runtime.participants.resolve(source=left.source, entity=left.entity)
        second = self._runtime.participants.resolve(source=right.source, entity=right.entity)
        return (
            first is not None
            and second is not None
            and first.participant_id == second.participant_id
        )

    def matches_speaker(self, candidate: TurnCandidate, record: AddressingEvidenceRecord) -> bool:
        if candidate.has_entity_conflict:
            return False

        left, right = candidate.speaker, record.evidence.speaker
        if left.entity is not None and right.entity is not None:
            if left.source == right.source and left.entity != right.entity:
                return False
            return self.same_subject(left, right)

        segment = record.target_segment
        if (
            segment not in candidate.segments
            or left.source != segment.source
            or right.source != segment.source
        ):
            return False
        if left.entity is None and right.entity is None:
            return True

        # A late entity can corroborate earlier anonymous evidence only for this exact segment.
        entity = left.entity or right.entity
        associated = self._runtime.participants.entity_for_segment(segment)
        observation = self._runtime.perception.timeline.get_observation(
            observation_id=record.target_observation_id
        )
        observed = (
            observation.entity
            if observation is not None and observation.segment == segment
            else None
        )
        proofs = [item for item in (associated, observed) if item is not None]
        return bool(proofs) and all(item.entity_id == entity.entity_id for item in proofs)

    def match_unsegmented(
        self, record: AddressingEvidenceRecord, candidates: Mapping[SpeakerKey, TurnCandidate]
    ) -> tuple[SpeakerKey, TurnCandidate] | None:
        if record.target_time_range is None:
            return None
        target = record.target_time_range.end.monotonic_ns
        matches: list[tuple[int, SpeakerKey, TurnCandidate]] = []
        for key, candidate in candidates.items():
            distance = max(
                0,
                candidate.started_at.monotonic_ns - target,
                target - candidate.updated_at.monotonic_ns,
            )
            if distance <= self._unsegmented_alignment_ns and self.same_subject(
                candidate.speaker, record.evidence.speaker
            ):
                matches.append((distance, key, candidate))

        matches.sort(key=lambda item: item[0], reverse=True)
        if not matches or len(matches) > 1 and matches[0][0] == matches[1][0]:
            return None
        _, key, candidate = matches[0]
        return key, candidate

    def ready(self, candidate: TurnCandidate) -> bool:
        if not self._required_addressing_sources:
            return True
        return bool(candidate.segments) and all(
            (record := candidate.addressing_evidence.get(source)) is not None
            and record.target_segment == candidate.segments[-1]
            for source in self._required_addressing_sources
        )

    def resolve(self, candidate: TurnCandidate) -> InteractionAddressingEvidence | None:
        return self._fusion.resolve(candidate.addressing_evidence.values())

    def update(
        self, candidate: TurnCandidate, record: AddressingEvidenceRecord, *, speaker_changed: bool
    ) -> bool:
        was_ready = self.ready(candidate)
        previous = self.resolve(candidate)
        if not candidate.update_addressing_evidence(record):
            return False

        if (
            not speaker_changed
            and was_ready == self.ready(candidate)
            and self._fusion.same_target(previous, self.resolve(candidate))
        ):
            return False
        candidate.mark_addressing_changed()
        return True

    def apply(
        self, assessment: TurnTakingAssessment, candidate: TurnCandidate
    ) -> TurnTakingAssessment:
        return self._fusion.apply(
            assessment=assessment, records=candidate.addressing_evidence.values()
        )
