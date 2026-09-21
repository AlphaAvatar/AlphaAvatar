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

import asyncio
from collections.abc import Hashable
from dataclasses import replace
from typing import TypeVar

from alphaavatar.agents.router import (
    InteractionAddressingEvidence,
    TurnTakingAction,
    TurnTakingAssessment,
    TurnTakingDecision,
    TurnTakingEvidence,
    TurnTakingModelBase,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import (
    AnnotationKind,
    EnvObservation,
    ObservationKind,
    PerceptionSegmentRef,
)
from alphaavatar.core.perception import PerceptionEvent

from ...log import logger
from .evidence import TurnEvidenceBuilder
from .fusion import DefaultAddressingFusion
from .policy import DefaultTurnTakingPolicy, TurnTakingPolicyResult
from .schemas.state import AddressingEvidenceRecord, SpeakerKey, TurnCandidate

_Key = TypeVar("_Key", bound=Hashable)


class TurnTakingCoordinator:
    SOURCE = "router.turn_taking"

    _MAX_ORPHANS = 64
    _MAX_ADDRESSING_RECORDS_PER_TARGET = 8
    _TERMINAL_ACTIONS = {
        TurnTakingAction.COMMIT,
        TurnTakingAction.CANCEL,
        TurnTakingAction.PASSIVE,
        TurnTakingAction.PROACTIVE_CHECK,
    }

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        model: TurnTakingModelBase,
        policy: DefaultTurnTakingPolicy,
        fusion: DefaultAddressingFusion,
        addressing_wait_sec: float,
        transcript_wait_sec: float,
        max_hold_sec: float,
        unsegmented_alignment_sec: float,
        required_addressing_sources: tuple[str, ...] = (),
    ) -> None:
        self._runtime = runtime
        self._model = model
        self._policy = policy
        self._fusion = fusion
        self._builder = TurnEvidenceBuilder(runtime)

        self._addressing_wait_sec = addressing_wait_sec
        self._transcript_wait_sec = transcript_wait_sec
        self._max_hold_sec = max_hold_sec
        self._unsegmented_alignment_ns = int(unsegmented_alignment_sec * 1_000_000_000)
        self._required_addressing_sources = frozenset(required_addressing_sources)

        self._candidates: dict[SpeakerKey, TurnCandidate] = {}
        self._segment_owners: dict[PerceptionSegmentRef, SpeakerKey] = {}
        self._orphan_transcripts: dict[PerceptionSegmentRef, EnvObservation] = {}
        self._orphan_addressing_by_observation: dict[str, list[AddressingEvidenceRecord]] = {}
        self._orphan_addressing_by_segment: dict[
            PerceptionSegmentRef, list[AddressingEvidenceRecord]
        ] = {}
        self._orphan_unsegmented_addressing: dict[str, AddressingEvidenceRecord] = {}

        self._assessment_tasks: dict[SpeakerKey, asyncio.Task[None]] = {}

    @staticmethod
    def _speaker_matches(
        candidate: TurnCandidate,
        evidence: InteractionAddressingEvidence,
    ) -> bool:
        candidate_entity = candidate.speaker.entity
        evidence_entity = evidence.speaker.entity

        if (
            candidate_entity is not None
            and evidence_entity is not None
            and candidate_entity.perception_entity_id != evidence_entity.perception_entity_id
        ):
            return False

        candidate_participant = candidate.speaker.transport_participant_id
        evidence_participant = evidence.speaker.transport_participant_id
        return not (
            candidate_participant is not None
            and evidence_participant is not None
            and candidate_participant != evidence_participant
        )

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

    def _store_unsegmented_addressing(self, record: AddressingEvidenceRecord) -> None:
        if (
            record.annotation_id not in self._orphan_unsegmented_addressing
            and len(self._orphan_unsegmented_addressing) >= self._MAX_ORPHANS
        ):
            self._orphan_unsegmented_addressing.pop(next(iter(self._orphan_unsegmented_addressing)))

        self._orphan_unsegmented_addressing[record.annotation_id] = record

    def _publish_result(
        self,
        candidate: TurnCandidate,
        result: TurnTakingPolicyResult,
        *,
        observation_id: str | None = None,
    ) -> None:
        decision = result.decision
        if (
            decision.turn_candidate_id != candidate.turn_candidate_id
            or decision.candidate_revision != candidate.revision
        ):
            return

        target_observation_id = observation_id or candidate.anchor_observation_id
        if target_observation_id is None:
            return

        if result.addressing is not None:
            self._runtime.perception.publish_annotation(
                result.addressing.to_annotation(
                    source=self.SOURCE,
                    observation_id=target_observation_id,
                )
            )

        self._runtime.perception.publish_annotation(
            decision.to_annotation(
                source=self.SOURCE,
                observation_id=target_observation_id,
            )
        )

    """Assessment Helper"""

    def _candidate(
        self,
        key: SpeakerKey,
        turn_candidate_id: str,
    ) -> TurnCandidate | None:
        candidate = self._candidates.get(key)
        if candidate is None or candidate.turn_candidate_id != turn_candidate_id:
            return None
        return candidate

    def _is_current(self, key: SpeakerKey, evidence: TurnTakingEvidence) -> bool:
        candidate = self._candidates.get(key)
        return (
            candidate is not None
            and candidate.turn_candidate_id == evidence.turn_candidate_id
            and candidate.revision == evidence.candidate_revision
        )

    @staticmethod
    def _operational_result(
        evidence: TurnTakingEvidence,
        *,
        action: TurnTakingAction,
        reason: str,
    ) -> TurnTakingPolicyResult:
        return TurnTakingPolicyResult(
            decision=TurnTakingDecision(
                turn_candidate_id=evidence.turn_candidate_id,
                candidate_revision=evidence.candidate_revision,
                turn_mode=evidence.turn_mode,
                action=action,
                confidence=0.0 if action == TurnTakingAction.HOLD else 1.0,
                actor=evidence.speaker,
                input_observation_ids=evidence.input_observation_ids,
                reason=reason,
            )
        )

    def _drop_candidate(self, key: SpeakerKey) -> None:
        candidate = self._candidates.pop(key, None)
        if candidate is None:
            return

        task = self._assessment_tasks.pop(key, None)
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

        for segment in candidate.segments:
            if self._segment_owners.get(segment) == key:
                self._segment_owners.pop(segment, None)

            self._orphan_transcripts.pop(segment, None)
            self._orphan_addressing_by_segment.pop(segment, None)

    def _cancel_assessment(self, key: SpeakerKey) -> None:
        task = self._assessment_tasks.pop(key, None)
        if task is not None and not task.done():
            task.cancel()

    async def _wait_for_transcript(
        self,
        key: SpeakerKey,
        evidence: TurnTakingEvidence,
        *,
        reason: str,
    ) -> None:
        if not self._is_current(key, evidence):
            return

        candidate = self._candidates[key]
        if not candidate.missing_transcripts:
            return

        self._publish_result(
            candidate,
            self._operational_result(
                evidence,
                action=TurnTakingAction.HOLD,
                reason=reason,
            ),
        )

        await asyncio.sleep(self._transcript_wait_sec)

        if not self._is_current(key, evidence):
            return

        candidate = self._candidates[key]
        if not candidate.missing_transcripts:
            return

        self._publish_result(
            candidate,
            self._operational_result(
                evidence,
                action=TurnTakingAction.CANCEL,
                reason="transcript_timeout",
            ),
        )
        self._drop_candidate(key)

    async def _hold_then_resolve(
        self,
        key: SpeakerKey,
        evidence: TurnTakingEvidence,
        *,
        assessment: TurnTakingAssessment | None,
        timeout_sec: float,
        reason: str,
    ) -> None:
        await asyncio.sleep(timeout_sec)

        if not self._is_current(key, evidence):
            return

        candidate = self._candidates[key]
        if candidate.active_segments:
            return

        result = self._policy.resolve_timeout(
            evidence=evidence,
            assessment=assessment,
            reason=reason,
        )

        if result.decision.action == TurnTakingAction.COMMIT and candidate.missing_transcripts:
            await self._wait_for_transcript(
                key,
                evidence,
                reason="awaiting_transcript_after_turn_timeout",
            )
            return

        self._publish_result(candidate, result)
        self._drop_candidate(key)

    async def _assess_candidate(self, key: SpeakerKey, turn_candidate_id: str) -> None:
        try:
            candidate = self._candidate(key, turn_candidate_id)
            if candidate is None or candidate.active_segments:
                return

            evidence = self._builder.build(candidate)

            if not self._model.capabilities.supports(evidence.turn_mode):
                self._publish_result(
                    candidate,
                    self._operational_result(
                        evidence,
                        action=TurnTakingAction.CANCEL,
                        reason=f"unsupported_turn_mode:{evidence.turn_mode.value}",
                    ),
                )
                self._drop_candidate(key)
                return

            if self._model.capabilities.uses_transcript and candidate.missing_transcripts:
                await self._wait_for_transcript(
                    key,
                    evidence,
                    reason="awaiting_transcript_for_assessment",
                )
                return

            try:
                assessment = await self._model.assess(evidence)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Turn assessment failed turn_candidate_id=%s model=%s",
                    evidence.turn_candidate_id,
                    self._model.name,
                )
                self._publish_result(
                    candidate,
                    self._operational_result(
                        evidence,
                        action=TurnTakingAction.HOLD,
                        reason="turn_assessment_error",
                    ),
                )
                await self._hold_then_resolve(
                    key,
                    evidence,
                    assessment=None,
                    timeout_sec=self._max_hold_sec,
                    reason="assessment_error_timeout",
                )
                return

            if not self._is_current(key, evidence):
                logger.debug(
                    "Discarded stale turn assessment turn_candidate_id=%s revision=%s",
                    evidence.turn_candidate_id,
                    evidence.candidate_revision,
                )
                return

            candidate = self._candidates[key]
            if not self._addressing_ready(candidate):
                self._publish_result(
                    candidate,
                    self._operational_result(
                        evidence,
                        action=TurnTakingAction.HOLD,
                        reason="awaiting_addressing",
                    ),
                )

                await asyncio.sleep(self._addressing_wait_sec)
                if not self._is_current(key, evidence):
                    return

                candidate = self._candidates[key]
                if not self._addressing_ready(candidate):
                    result = self._policy.resolve_timeout(
                        evidence=evidence,
                        assessment=assessment,
                        reason="addressing_timeout",
                    )
                    self._publish_result(candidate, result)
                    self._drop_candidate(key)
                    return

            assessment = self._fusion.apply(
                assessment=assessment,
                records=candidate.addressing_evidence.values(),
            )
            result = self._policy.decide(
                evidence=evidence,
                assessment=assessment,
            )

            if result.decision.action == TurnTakingAction.COMMIT and candidate.missing_transcripts:
                await self._wait_for_transcript(
                    key,
                    evidence,
                    reason="awaiting_transcript_for_commit",
                )
                return

            self._publish_result(candidate, result)

            if result.decision.action == TurnTakingAction.HOLD:
                waiting_for_addressing = result.decision.reason == "addressing_unknown"

                await self._hold_then_resolve(
                    key,
                    evidence,
                    assessment=assessment,
                    timeout_sec=(
                        self._addressing_wait_sec if waiting_for_addressing else self._max_hold_sec
                    ),
                    reason=(
                        "addressing_timeout" if waiting_for_addressing else "turn_hold_timeout"
                    ),
                )

            elif result.decision.action in self._TERMINAL_ACTIONS:
                self._drop_candidate(key)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Turn assessment task failed turn_candidate_id=%s",
                turn_candidate_id,
            )
        finally:
            if self._assessment_tasks.get(key) is asyncio.current_task():
                self._assessment_tasks.pop(key, None)

    def _schedule_assessment(self, key: SpeakerKey, turn_candidate_id: str) -> None:
        self._cancel_assessment(key)
        self._assessment_tasks[key] = asyncio.create_task(
            self._assess_candidate(key, turn_candidate_id),
            name=f"router_turn_assessment:{turn_candidate_id}",
        )

    """Addressing Helper"""

    def _addressing_ready(self, candidate: TurnCandidate) -> bool:
        if not self._required_addressing_sources:
            return True
        if not candidate.segments:
            return False

        latest_segment = candidate.segments[-1]

        return all(
            (record := candidate.addressing_evidence.get(source)) is not None
            and record.target_segment == latest_segment
            for source in self._required_addressing_sources
        )

    def _current_addressing(
        self,
        candidate: TurnCandidate,
    ) -> InteractionAddressingEvidence | None:
        return self._fusion.resolve(candidate.addressing_evidence.values())

    def _maybe_interrupt(self, candidate: TurnCandidate, observation_id: str) -> None:
        if candidate.interruption_requested:
            return

        evidence = self._builder.build(candidate)
        result = self._policy.decide_interruption(
            evidence=evidence,
            addressing=self._current_addressing(candidate),
        )
        if result is None or not candidate.claim_interruption():
            return

        self._publish_result(candidate, result, observation_id=observation_id)
        logger.debug(
            "Turn interruption requested turn_candidate_id=%s revision=%s mode=%s",
            candidate.turn_candidate_id,
            candidate.revision,
            evidence.turn_mode.value,
        )

    def _apply_addressing(
        self,
        key: SpeakerKey,
        candidate: TurnCandidate,
        record: AddressingEvidenceRecord,
    ) -> None:
        if not self._speaker_matches(candidate, record.evidence):
            logger.warning(
                "Addressing evidence speaker mismatch turn_candidate_id=%s annotation_id=%s",
                candidate.turn_candidate_id,
                record.annotation_id,
            )
            return

        was_ready = self._addressing_ready(candidate)
        previous = self._current_addressing(candidate)

        if not candidate.update_addressing_evidence(record):
            return

        is_ready = self._addressing_ready(candidate)
        current = self._current_addressing(candidate)

        if was_ready == is_ready and self._fusion.same_target(previous, current):
            return

        candidate.mark_addressing_changed()
        self._cancel_assessment(key)

        if candidate.active_segments:
            self._maybe_interrupt(candidate, record.target_observation_id)
        else:
            self._schedule_assessment(key, candidate.turn_candidate_id)

    def _attach_segment_addressing(
        self,
        key: SpeakerKey,
        candidate: TurnCandidate,
        segment: PerceptionSegmentRef,
    ) -> None:
        for record in self._orphan_addressing_by_segment.pop(segment, ()):
            self._apply_addressing(key, candidate, record)

    @staticmethod
    def _identity_score(
        candidate: TurnCandidate,
        record: AddressingEvidenceRecord,
    ) -> int | None:
        candidate_participant = candidate.speaker.transport_participant_id
        evidence_participant = record.evidence.speaker.transport_participant_id
        if (
            candidate_participant is not None
            and evidence_participant is not None
            and candidate_participant != evidence_participant
        ):
            return None

        candidate_entity = candidate.speaker.entity
        evidence_entity = record.evidence.speaker.entity
        if candidate_entity is not None and evidence_entity is not None:
            return (
                3
                if candidate_entity.perception_entity_id == evidence_entity.perception_entity_id
                else None
            )

        if candidate_participant is not None and evidence_participant is not None:
            return 2

        return None

    @staticmethod
    def _temporal_distance_ns(
        candidate: TurnCandidate,
        record: AddressingEvidenceRecord,
    ) -> int | None:
        if record.target_time_range is None:
            return None

        target_ns = record.target_time_range.end.monotonic_ns
        start_ns = candidate.started_at.monotonic_ns
        end_ns = candidate.updated_at.monotonic_ns
        if start_ns <= target_ns <= end_ns:
            return 0

        return min(abs(target_ns - start_ns), abs(target_ns - end_ns))

    def _match_unsegmented(
        self,
        record: AddressingEvidenceRecord,
    ) -> tuple[SpeakerKey, TurnCandidate] | None:
        matches: list[tuple[int, int, SpeakerKey, TurnCandidate]] = []

        for key, candidate in self._candidates.items():
            identity_score = self._identity_score(candidate, record)
            distance_ns = self._temporal_distance_ns(candidate, record)
            if (
                identity_score is None
                or distance_ns is None
                or distance_ns > self._unsegmented_alignment_ns
            ):
                continue

            matches.append((identity_score, -distance_ns, key, candidate))

        if not matches:
            return None

        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best = matches[0]
        if len(matches) > 1 and matches[1][:2] == best[:2]:
            return None

        return best[2], best[3]

    def _route_unsegmented_addressing(self, record: AddressingEvidenceRecord) -> None:
        match = self._match_unsegmented(record)
        if match is None:
            self._store_unsegmented_addressing(record)
            return

        key, candidate = match
        self._apply_addressing(key, candidate, record)

    def _retry_unsegmented_addressing(self) -> None:
        records = tuple(self._orphan_unsegmented_addressing.values())
        self._orphan_unsegmented_addressing.clear()

        for record in records:
            self._route_unsegmented_addressing(record)

    def _route_addressing(
        self,
        segment: PerceptionSegmentRef,
        record: AddressingEvidenceRecord,
    ) -> None:
        key = self._segment_owners.get(segment)
        if key is None:
            self._store_addressing(
                self._orphan_addressing_by_segment,
                segment,
                record,
            )
            return

        candidate = self._candidates.get(key)
        if candidate is not None:
            self._apply_addressing(key, candidate, record)

    def _route_observation_addressing(
        self,
        observation: EnvObservation,
        record: AddressingEvidenceRecord,
    ) -> None:
        record = replace(
            record,
            target_time_range=observation.time_range,
            target_segment=observation.segment,
        )

        if observation.segment is not None:
            self._route_addressing(observation.segment, record)
        else:
            self._route_unsegmented_addressing(record)

    def _attach_pending_addressing(self, observation: EnvObservation) -> None:
        for record in self._orphan_addressing_by_observation.pop(
            observation.observation_id,
            (),
        ):
            self._route_observation_addressing(observation, record)

    """Observation Handler"""

    def _get_candidate(
        self,
        observation: EnvObservation,
    ) -> tuple[SpeakerKey, TurnCandidate]:
        key = SpeakerKey.from_observation(observation)
        candidate = self._candidates.get(key)

        if candidate is None:
            candidate = TurnCandidate.create(observation)
            self._candidates[key] = candidate

        return key, candidate

    def _apply_transcript(
        self,
        key: SpeakerKey,
        candidate: TurnCandidate,
        segment: PerceptionSegmentRef,
        observation: EnvObservation,
    ) -> None:
        text = self._builder.text(observation)
        if (
            text is None
            or not candidate.add_transcript(segment, observation, text)
            or candidate.active_segments
        ):
            return

        self._schedule_assessment(key, candidate.turn_candidate_id)

    def _store_orphan_transcript(
        self,
        segment: PerceptionSegmentRef,
        observation: EnvObservation,
    ) -> None:
        if (
            segment not in self._orphan_transcripts
            and len(self._orphan_transcripts) >= self._MAX_ORPHANS
        ):
            self._orphan_transcripts.pop(next(iter(self._orphan_transcripts)))

        self._orphan_transcripts[segment] = observation

    def _consume_speech(self, observation: EnvObservation) -> None:
        segment = self._builder.require_segment(observation)
        key, candidate = self._get_candidate(observation)

        is_new_segment = candidate.start_segment(segment, observation)
        self._segment_owners[segment] = key

        if is_new_segment:
            candidate.add_input_observation(observation.observation_id)
            self._cancel_assessment(key)

        self._attach_segment_addressing(key, candidate, segment)

        if is_new_segment:
            self._retry_unsegmented_addressing()
            self._maybe_interrupt(candidate, observation.observation_id)

        orphan = self._orphan_transcripts.pop(segment, None)
        if orphan is not None:
            self._apply_transcript(key, candidate, segment, orphan)

        if observation.kind != ObservationKind.SPEECH_SEGMENT:
            return

        candidate.close_segment(segment, observation)

        audio = self._builder.audio(observation)
        if audio is not None:
            candidate.add_audio(audio)

        if not candidate.active_segments:
            self._schedule_assessment(key, candidate.turn_candidate_id)

    def _consume_transcript(self, observation: EnvObservation) -> None:
        segment = self._builder.require_segment(observation)
        key = self._segment_owners.get(segment)

        if key is None:
            self._store_orphan_transcript(segment, observation)
            return

        candidate = self._candidates.get(key)
        if candidate is not None:
            self._apply_transcript(key, candidate, segment, observation)

    def handle_observation(self, observation: EnvObservation) -> None:
        self._attach_pending_addressing(observation)

        if observation.kind in {
            ObservationKind.SPEECH_FRAME,
            ObservationKind.SPEECH_SEGMENT,
        }:
            self._consume_speech(observation)
        elif observation.kind == ObservationKind.TRANSCRIPT_SEGMENT:
            self._consume_transcript(observation)

    """Annotation Handler"""

    def handle_annotation(self, event: PerceptionEvent) -> None:
        annotation = event.annotation
        if annotation is None or annotation.kind != AnnotationKind.INTERACTION_ADDRESSING_EVIDENCE:
            return

        observation_id = annotation.observation_id
        if observation_id is None:
            logger.warning(
                "Addressing evidence has no observation target annotation_id=%s",
                annotation.annotation_id,
            )
            return

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
            self._store_addressing(
                self._orphan_addressing_by_observation,
                observation_id,
                record,
            )
            return

        self._route_observation_addressing(observation, record)

    def handle_annotation_gap(self) -> None:
        self._orphan_addressing_by_observation.clear()
        self._orphan_addressing_by_segment.clear()
        self._orphan_unsegmented_addressing.clear()

        for key, candidate in tuple(self._candidates.items()):
            if not candidate.mark_annotation_gap():
                continue

            self._cancel_assessment(key)
            if not candidate.active_segments:
                self._schedule_assessment(key, candidate.turn_candidate_id)

    async def reset(self) -> None:
        tasks = tuple(self._assessment_tasks.values())
        self._assessment_tasks.clear()

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._candidates.clear()
        self._segment_owners.clear()
        self._orphan_transcripts.clear()
        self._orphan_addressing_by_observation.clear()
        self._orphan_addressing_by_segment.clear()
        self._orphan_unsegmented_addressing.clear()
