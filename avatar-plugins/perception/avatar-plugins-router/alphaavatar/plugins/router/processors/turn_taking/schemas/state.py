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

from asyncio import TimerHandle
from dataclasses import dataclass, field
from uuid import uuid4

from alphaavatar.agents.router.enums import InteractionEntityKind
from alphaavatar.agents.router.schemas import (
    InteractionAddressingEvidence,
    InteractionEntityRef,
    TurnTakingAudioEvidence,
    TurnTakingDecision,
)
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.schemas import PerceptionSegmentRef, PerceptionSourceRef
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange


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
class TranscriptWait:
    deadline: float
    decision: TurnTakingDecision | None = None
    segments: frozenset[PerceptionSegmentRef] = frozenset()
    timer: TimerHandle | None = None

    def cancel_timer(self) -> None:
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None


@dataclass(slots=True)
class InputWindow:
    """Uncommitted interaction input, independent of its participants' identities."""

    started_at: RuntimeTime
    updated_at: RuntimeTime

    context_id: str
    input_id: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 0

    observed_sequence: int = 0
    sealed: bool = False
    published: bool = False
    admission_timer: TimerHandle | None = None
    interruption_requested: bool = False
    has_perception_gap: bool = False
    wait: TranscriptWait | None = None
    transcript_failure: str | None = None
    speech_completion_deadline: float | None = None
    addressing_deadline: float | None = None

    segments: list[PerceptionSegmentRef] = field(default_factory=list)
    active_segments: set[PerceptionSegmentRef] = field(default_factory=set)
    closed_segments: set[PerceptionSegmentRef] = field(default_factory=set)

    transcripts: dict[PerceptionSegmentRef, str] = field(default_factory=dict)
    unavailable_transcripts: dict[PerceptionSegmentRef, str | None] = field(default_factory=dict)
    audio: dict[PerceptionSegmentRef, TurnTakingAudioEvidence] = field(default_factory=dict)
    subjects: dict[PerceptionSegmentRef, InteractionEntityRef] = field(default_factory=dict)
    addressing_evidence: dict[tuple[str, str], AddressingEvidenceRecord] = field(
        default_factory=dict
    )

    input_observation_ids: list[str] = field(default_factory=list)
    anchor_observation_id: str | None = None
    latest_observation_id: str | None = None

    @property
    def sources(self) -> set[PerceptionSourceRef]:
        return {segment.source for segment in self.segments}

    @property
    def actors(self) -> tuple[InteractionEntityRef, ...]:
        return tuple(dict.fromkeys(self.subjects.values()))

    @property
    def pending_transcripts(self) -> set[PerceptionSegmentRef]:
        return self.closed_segments.difference(self.transcripts, self.unavailable_transcripts)

    @property
    def missing_transcripts(self) -> set[PerceptionSegmentRef]:
        return self.closed_segments.difference(self.transcripts)

    @property
    def text(self) -> str:
        return " ".join(self.transcripts[s] for s in self.segments if s in self.transcripts).strip()

    def _touch(self, at: RuntimeTime) -> None:
        self.updated_at = max(self.updated_at, at, key=lambda value: value.monotonic_ns)
        self.revision += 1

    def _subject(self, segment: PerceptionSegmentRef, observation: EnvObservation) -> None:
        previous = self.subjects.get(segment)
        if previous is None or previous.entity is None and observation.entity is not None:
            self.subjects[segment] = InteractionEntityRef(
                kind=InteractionEntityKind.PERSON,
                source=segment.source,
                entity=observation.entity,
                device_id=observation.device_id,
            )

    def add_input_observation(self, observation_id: str) -> None:
        if observation_id not in self.input_observation_ids:
            self.input_observation_ids.append(observation_id)

    def start_segment(self, segment: PerceptionSegmentRef, observation: EnvObservation) -> bool:
        self.latest_observation_id = observation.observation_id
        if self.sealed or segment in self.closed_segments:
            return False
        added = segment not in self.segments
        if added:
            self.segments.append(segment)
            self.speech_completion_deadline = self.addressing_deadline = None
        self._subject(segment, observation)
        if added or segment not in self.active_segments:
            self._touch(observation.time_range.end)
        self.active_segments.add(segment)
        return added

    def close_segment(self, segment: PerceptionSegmentRef, observation: EnvObservation) -> bool:
        if self.sealed or segment in self.closed_segments:
            return False

        if segment not in self.segments:
            self.segments.append(segment)

        self._subject(segment, observation)
        self.active_segments.discard(segment)
        self.closed_segments.add(segment)
        self.anchor_observation_id = self.latest_observation_id = observation.observation_id
        self.add_input_observation(observation.observation_id)
        self._touch(observation.time_range.end)
        return True

    def add_audio(self, evidence: TurnTakingAudioEvidence) -> None:
        self.audio[evidence.segment] = evidence

    def add_transcript(
        self, segment: PerceptionSegmentRef, observation: EnvObservation, text: str
    ) -> bool:
        if self.transcripts.get(segment) == text or segment in self.unavailable_transcripts:
            return False

        self.transcripts[segment] = text
        self.add_input_observation(observation.observation_id)
        self._touch(observation.time_range.end)
        return True

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
