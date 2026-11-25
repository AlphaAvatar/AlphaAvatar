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

from alphaavatar.agents.router.enums import (
    AddressingEvidenceKind,
    AddressingMode,
    AssessmentLabel,
    InteractionEntityKind,
    TurnTakingMode,
)
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
from .schemas.state import AddressingEvidenceRecord, InputWindow

logger = logging.getLogger(__name__)
_Key = TypeVar("_Key", bound=Hashable)


class TurnAddressing:
    """Correlate addressing by its observation, segment or time, without identifying people."""

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

    @staticmethod
    def _with_target(
        record: AddressingEvidenceRecord, observation: EnvObservation
    ) -> AddressingEvidenceRecord:
        return replace(
            record, target_time_range=observation.time_range, target_segment=observation.segment
        )

    @staticmethod
    def _distance(window: InputWindow, record: AddressingEvidenceRecord) -> int | None:
        target = record.target_time_range
        if target is None:
            return None
        return max(
            0,
            window.started_at.monotonic_ns - target.end.monotonic_ns,
            target.start.monotonic_ns - window.updated_at.monotonic_ns,
        )

    @staticmethod
    def _has_observation(window: InputWindow, record: AddressingEvidenceRecord) -> bool:
        return (
            record.target_observation_id in window.input_observation_ids
            or record.target_observation_id == window.latest_observation_id
        )

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

        try:
            evidence = InteractionAddressingEvidence.from_annotation(annotation)
        except (AttributeError, KeyError, TypeError, ValueError):
            logger.warning("Invalid addressing evidence annotation_id=%s", annotation.annotation_id)
            return None

        record = AddressingEvidenceRecord(
            annotation_id=annotation.annotation_id,
            source=annotation.source,
            sequence=event.sequence,
            target_observation_id=observation_id,
            published_at=event.time_range.end,
            evidence=evidence,
        )
        observation = self._runtime.perception.timeline.get_observation(
            observation_id=observation_id
        )

        if observation is None:
            self._store_addressing(self._by_observation, observation_id, record)
            return None

        return self._with_target(record, observation)

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

    def matches(self, window: InputWindow, record: AddressingEvidenceRecord) -> bool:
        # Explicit segment references include the source generation. Time proximity never
        # overrides a reference to another window, nor supplies a missing speaker identity.
        if record.target_segment is not None:
            return record.target_segment in window.segments
        if self._has_observation(window, record):
            return True
        distance = self._distance(window, record)
        return distance is not None and distance <= self._unsegmented_alignment_ns

    def match_window(
        self, record: AddressingEvidenceRecord, windows: Mapping[str, InputWindow]
    ) -> tuple[str, InputWindow] | None:
        matches: list[tuple[int, int, str, InputWindow]] = []
        for key, window in windows.items():
            if not self.matches(window, record):
                continue
            exact = record.target_segment is not None or self._has_observation(window, record)
            distance = 0 if exact else self._distance(window, record)
            if distance is not None:
                matches.append((0 if exact else 1, distance, key, window))

        matches.sort(key=lambda item: item[:2])
        if not matches or len(matches) > 1 and matches[0][:2] == matches[1][:2]:
            return None
        _, _, key, window = matches[0]
        return key, window

    def ready(self, window: InputWindow) -> bool:
        if not self._required_addressing_sources:
            return True
        return bool(window.segments) and all(
            any(
                record.source == source and record.target_segment == window.segments[-1]
                for record in window.addressing_evidence.values()
            )
            for source in self._required_addressing_sources
        )

    def _records(self, window: InputWindow) -> tuple[AddressingEvidenceRecord, ...]:
        # Semantic judgments include the accumulated window up to their target. An older
        # segment's result cannot stand in for a judgment of newly appended speech.
        last = window.segments[-1] if window.segments else None
        return tuple(
            record
            for record in window.addressing_evidence.values()
            if record.evidence.evidence_kind
            not in {AddressingEvidenceKind.SEMANTIC, AddressingEvidenceKind.CONVERSATION_FOCUS}
            or record.target_segment == last
        )

    def resolve(self, window: InputWindow) -> InteractionAddressingEvidence | None:
        return self._fusion.resolve(self._records(window))

    def update(self, window: InputWindow, record: AddressingEvidenceRecord) -> bool:
        if not self.matches(window, record):
            return False

        key = (record.source, record.target_observation_id)
        previous = window.addressing_evidence.get(key)
        if previous is not None and (
            previous.sequence >= record.sequence or previous.annotation_id == record.annotation_id
        ):
            return False

        window.addressing_evidence[key] = record
        window.revision += 1
        return True

    def apply(self, assessment: TurnTakingAssessment, window: InputWindow) -> TurnTakingAssessment:
        if (
            assessment.turn_mode == TurnTakingMode.AUDIO_ONLY
            and not self._required_addressing_sources
            and not window.addressing_evidence
        ):
            return replace(
                assessment,
                addressing=AssessmentLabel.POSITIVE,
                addressees=(InteractionEntityRef(kind=InteractionEntityKind.AVATAR),),
                addressing_mode=AddressingMode.DIRECT,
                addressing_confidence=1.0,
            )

        return self._fusion.apply(assessment=assessment, records=self._records(window))
