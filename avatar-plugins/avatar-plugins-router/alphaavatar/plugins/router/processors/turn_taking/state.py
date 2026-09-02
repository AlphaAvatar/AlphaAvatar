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

from dataclasses import dataclass, field
from uuid import uuid4

from alphaavatar.agents.interaction import (
    InteractionAddressingEvidence,
    InteractionEntityKind,
    InteractionEntityRef,
    TurnTakingAudioEvidence,
)
from alphaavatar.core.env import (
    EnvObservation,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange


@dataclass(frozen=True, slots=True)
class SpeakerKey:
    source: PerceptionSourceRef
    perception_entity_id: str | None
    transport_participant_id: str | None

    @classmethod
    def from_observation(cls, observation: EnvObservation) -> SpeakerKey:
        entity = observation.entity
        return cls(
            source=observation.segment.source if observation.segment else observation.source,
            perception_entity_id=entity.perception_entity_id if entity else None,
            transport_participant_id=observation.transport_participant_id,
        )


@dataclass(frozen=True, slots=True)
class AddressingEvidenceRecord:
    annotation_id: str
    source: str
    sequence: int
    target_observation_id: str
    published_at: RuntimeTime
    evidence: InteractionAddressingEvidence

    target_time_range: RuntimeTimeRange | None = None
    target_segment: PerceptionSegmentRef | None = None


@dataclass(slots=True)
class TurnCandidate:
    key: SpeakerKey
    speaker: InteractionEntityRef
    started_at: RuntimeTime
    updated_at: RuntimeTime

    turn_candidate_id: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 0
    interruption_requested: bool = False
    has_perception_gap: bool = False

    segments: list[PerceptionSegmentRef] = field(default_factory=list)
    active_segments: set[PerceptionSegmentRef] = field(default_factory=set)
    closed_segments: set[PerceptionSegmentRef] = field(default_factory=set)

    transcripts: dict[PerceptionSegmentRef, str] = field(default_factory=dict)
    audio: dict[PerceptionSegmentRef, TurnTakingAudioEvidence] = field(default_factory=dict)
    addressing_evidence: dict[str, AddressingEvidenceRecord] = field(default_factory=dict)

    input_observation_ids: list[str] = field(default_factory=list)
    anchor_observation_id: str | None = None

    @property
    def missing_transcripts(self) -> set[PerceptionSegmentRef]:
        return self.closed_segments.difference(self.transcripts)

    @property
    def text(self) -> str:
        return " ".join(
            self.transcripts[segment] for segment in self.segments if segment in self.transcripts
        ).strip()

    @classmethod
    def create(cls, observation: EnvObservation) -> TurnCandidate:
        key = SpeakerKey.from_observation(observation)
        return cls(
            key=key,
            speaker=InteractionEntityRef(
                kind=InteractionEntityKind.PERSON,
                entity=observation.entity,
                transport_participant_id=observation.transport_participant_id,
            ),
            started_at=observation.time_range.start,
            updated_at=observation.time_range.end,
        )

    def _touch(self, at: RuntimeTime) -> None:
        self.updated_at = at
        self.revision += 1

    def start_segment(
        self,
        segment: PerceptionSegmentRef,
        observation: EnvObservation,
    ) -> bool:
        is_new = segment not in self.segments
        was_active = segment in self.active_segments

        if is_new:
            self.segments.append(segment)

        self.active_segments.add(segment)
        if is_new or not was_active:
            self._touch(observation.time_range.end)
        else:
            self.updated_at = observation.time_range.end

        return is_new

    def close_segment(
        self,
        segment: PerceptionSegmentRef,
        observation: EnvObservation,
    ) -> None:
        is_new = segment not in self.segments
        was_closed = segment in self.closed_segments

        if is_new:
            self.segments.append(segment)
            self.started_at = observation.time_range.start

        self.active_segments.discard(segment)
        self.closed_segments.add(segment)
        self.anchor_observation_id = observation.observation_id
        self.add_input_observation(observation.observation_id)

        if is_new or not was_closed:
            self._touch(observation.time_range.end)
        else:
            self.updated_at = observation.time_range.end

    def add_audio(self, evidence: TurnTakingAudioEvidence) -> bool:
        if self.audio.get(evidence.segment) == evidence:
            return False

        self.audio[evidence.segment] = evidence
        self._touch(evidence.time_range.end)
        return True

    def add_transcript(
        self,
        segment: PerceptionSegmentRef,
        observation: EnvObservation,
        text: str,
    ) -> bool:
        if self.transcripts.get(segment) == text:
            return False

        self.transcripts[segment] = text
        self.add_input_observation(observation.observation_id)
        self._touch(observation.time_range.end)
        return True

    def add_input_observation(self, observation_id: str) -> None:
        if observation_id not in self.input_observation_ids:
            self.input_observation_ids.append(observation_id)

    def update_addressing_evidence(self, record: AddressingEvidenceRecord) -> bool:
        previous = self.addressing_evidence.get(record.source)
        if previous is not None and previous.sequence >= record.sequence:
            return False

        self.addressing_evidence[record.source] = record
        return True

    def mark_addressing_changed(self) -> None:
        self.revision += 1

    def mark_annotation_gap(self) -> bool:
        if self.has_perception_gap and not self.addressing_evidence:
            return False

        self.addressing_evidence.clear()
        self.has_perception_gap = True
        self.revision += 1
        return True

    def claim_interruption(self) -> bool:
        if self.interruption_requested:
            return False

        self.interruption_requested = True
        return True
