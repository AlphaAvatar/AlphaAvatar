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
import logging
from dataclasses import replace
from math import isfinite

from alphaavatar.agents.router.enums import InteractionEntityKind, TurnTakingAction
from alphaavatar.agents.router.models import TurnTakingModelBase
from alphaavatar.agents.router.schemas import TurnTakingDecision, TurnTakingEvidence
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind, SpeechCancellationReason
from alphaavatar.core.env.schemas import PerceptionSegmentRef, PerceptionSourceRef
from alphaavatar.core.perception.schemas import PerceptionEvent
from alphaavatar.core.session.schemas import IdentityRef

from .addressing import TurnAddressing
from .evidence import TurnEvidenceBuilder
from .fusion import AddressingFusion
from .policy import TurnTakingPolicy, TurnTakingPolicyResult
from .schemas.state import AddressingEvidenceRecord, SpeakerKey, TurnCandidate

logger = logging.getLogger(__name__)


class TurnTakingCoordinator:
    SOURCE = "router.turn_taking"

    _MAX_ORPHANS = 64
    _MAX_RETIRED_SEGMENTS = 256
    _MAX_CANCELLED_SOURCES = 256
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
        policy: TurnTakingPolicy,
        fusion: AddressingFusion,
        addressing_wait_sec: float,
        transcript_wait_sec: float,
        max_hold_sec: float,
        unsegmented_alignment_sec: float,
        association_wait_sec: float = 0.15,
        transcript_timeout_sec: float = 3.0,
        transcript_timeout_notice_code: str | None = None,
        required_addressing_sources: tuple[str, ...] = (),
        max_active_candidates: int = 128,
    ) -> None:
        if type(max_active_candidates) is not int or max_active_candidates <= 0:
            raise ValueError("max_active_candidates must be a positive integer")
        if not isfinite(association_wait_sec) or association_wait_sec < 0:
            raise ValueError("association_wait_sec must be finite and nonnegative")
        if not isfinite(transcript_timeout_sec) or transcript_timeout_sec <= 0:
            raise ValueError("transcript_timeout_sec must be finite and positive")

        self._max_active_candidates = max_active_candidates
        self._runtime = runtime
        self._model = model
        self._policy = policy
        self._addressing = TurnAddressing(
            runtime=runtime,
            fusion=fusion,
            alignment_sec=unsegmented_alignment_sec,
            required_sources=required_addressing_sources,
        )
        self._builder = TurnEvidenceBuilder(runtime)

        self._addressing_wait_sec = addressing_wait_sec
        self._transcript_wait_sec = transcript_wait_sec
        self._transcript_timeout_sec = transcript_timeout_sec
        self._transcript_timeout_notice_code = transcript_timeout_notice_code
        self._association_wait_sec = association_wait_sec
        self._max_hold_sec = max_hold_sec

        self._candidates: dict[SpeakerKey, TurnCandidate] = {}
        self._segment_owners: dict[PerceptionSegmentRef, SpeakerKey] = {}
        self._retired_segments: dict[PerceptionSegmentRef, None] = {}
        self._cancelled_sources: dict[PerceptionSourceRef, None] = {}
        self._orphan_transcripts: dict[PerceptionSegmentRef, EnvObservation] = {}

        self._assessment_tasks: dict[SpeakerKey, asyncio.Task[None]] = {}
        self._assessment_workers: set[asyncio.Task[None]] = set()
        self._speech_order = self._committed_speech_order = 0

    def _refresh_speaker(
        self, candidate: TurnCandidate, observation: EnvObservation | None = None
    ) -> bool:
        if candidate.has_entity_conflict:
            return False

        entities = {}
        if candidate.speaker.entity is not None:
            entities[candidate.speaker.entity.entity_id] = candidate.speaker.entity
        if observation is not None and observation.segment in candidate.segments:
            if observation.entity is not None:
                entities[observation.entity.entity_id] = observation.entity
        for segment in candidate.segments:
            entity = self._runtime.participants.entity_for_segment(segment)
            if entity is not None:
                entities[entity.entity_id] = entity

        if len(entities) > 1:
            # Conflicting entity evidence cannot leave a valid owner for Engine to reconstruct.
            for segment in candidate.segments:
                associated = self._runtime.participants.entity_for_segment(segment)
                if (
                    candidate.speaker.entity is None
                    or associated is not None
                    and associated != candidate.speaker.entity
                    or observation is not None
                    and observation.segment == segment
                    and observation.entity is not None
                    and observation.entity != candidate.speaker.entity
                ):
                    self._runtime.participants.invalidate_segment(segment)
            candidate.has_entity_conflict = candidate.has_perception_gap = True
            candidate.addressing_evidence.clear()
            entity = None
        else:
            entity = next(iter(entities.values()), None)
            if entity == candidate.speaker.entity:
                return False

        candidate.speaker = replace(candidate.speaker, entity=entity)
        candidate.revision += 1
        self._cancel_assessment(candidate.key)
        return True

    def _related_speech(self, left: TurnCandidate, right: TurnCandidate) -> bool:
        return left.key.source == right.key.source and (
            left.speaker.entity is None
            or right.speaker.entity is None
            or self._addressing.same_subject(left.speaker, right.speaker)
        )

    def _speech_active(self, candidate: TurnCandidate) -> bool:
        return (
            bool(candidate.active_segments)
            or candidate.transcript_deadline is None
            and any(
                other.active_segments and self._related_speech(candidate, other)
                for other in self._candidates.values()
            )
        )

    def _resume_source(self, source: PerceptionSourceRef) -> None:
        if source in self._cancelled_sources or not self._runtime.participants.source_is_current(
            source
        ):
            return

        # Resolve all subjects before testing continuation; either candidate may have changed.
        for key, candidate in tuple(self._candidates.items()):
            if key.source == source:
                self._refresh_speaker(candidate)
        for key, candidate in tuple(self._candidates.items()):
            task = self._assessment_tasks.get(key)
            if key.source == source and (task is None or task.done()):
                self._schedule_assessment(key, candidate.turn_candidate_id)

    def _publish_result(
        self,
        candidate: TurnCandidate,
        result: TurnTakingPolicyResult,
        *,
        observation_id: str | None = None,
    ) -> None:
        decision = result.decision
        if (
            self._candidates.get(candidate.key) is not candidate
            or candidate.context_id != self._runtime.state.context_id
            or decision.turn_candidate_id != candidate.turn_candidate_id
            or decision.candidate_revision != candidate.revision
        ):
            return

        target_observation_id = observation_id or candidate.anchor_observation_id
        if target_observation_id is None:
            return

        if (
            decision.action == TurnTakingAction.COMMIT
            and candidate.transcript_deadline is not None
            and candidate.speech_order < self._committed_speech_order
        ):
            result = self._operational_result(
                self._builder.build(candidate),
                action=TurnTakingAction.CANCEL,
                reason="superseded_transcript",
            )
            decision = result.decision
        elif decision.action == TurnTakingAction.COMMIT and candidate.unavailable_transcripts:
            result = self._with_transcript_notice(candidate, result)
            decision = result.decision

        if result.addressing is not None:
            self._runtime.perception.publish_annotation(
                result.addressing.to_annotation(
                    source=self.SOURCE, observation_id=target_observation_id
                )
            )

        annotation = decision.to_annotation(
            source=self.SOURCE, observation_id=target_observation_id
        )
        annotation = replace(
            annotation, data={**annotation.data, "context_id": candidate.context_id}
        )
        event = self._runtime.perception.publish_annotation(annotation)
        if event is not None and decision.action == TurnTakingAction.COMMIT:
            self._committed_speech_order = max(self._committed_speech_order, candidate.speech_order)
        trace = self._runtime.perception.input_trace
        trace.record(
            "candidate.decision",
            candidate_id=candidate.turn_candidate_id,
            candidate_revision=candidate.revision,
            decision_id=annotation.annotation_id,
            observation_id=target_observation_id,
            event_id=event.event_id if event is not None else None,
            sequence=event.sequence if event is not None else None,
            action=decision.action.value,
            outcome="published" if event is not None else "not_published",
            evidence_count=len(decision.input_observation_ids),
            missing_count=len(candidate.missing_transcripts),
        )
        if decision.action == TurnTakingAction.CANCEL:
            trace.freeze(reason="candidate_cancelled")

        logger.debug(
            "TURN DECISION candidate_id=%s revision=%s action=%s reason=%s mode=%s "
            "segments=%d active_segments=%d missing_transcripts=%d",
            candidate.turn_candidate_id,
            candidate.revision,
            decision.action.value,
            decision.reason,
            decision.turn_mode.value,
            len(candidate.segments),
            len(candidate.active_segments),
            len(candidate.missing_transcripts),
        )

    """Assessment Helper"""

    def _candidate(self, key: SpeakerKey, turn_candidate_id: str) -> TurnCandidate | None:
        candidate = self._candidates.get(key)
        if candidate is None or candidate.turn_candidate_id != turn_candidate_id:
            return None
        return candidate

    def _is_current(self, key: SpeakerKey, evidence: TurnTakingEvidence) -> bool:
        candidate = self._candidate(key, evidence.turn_candidate_id)
        if candidate is None:
            return False
        if candidate.transcript_deadline is not None and not self._pending_is_current(candidate):
            self._drop_candidate(key)
            return False
        if self._refresh_speaker(candidate):
            self._schedule_assessment(key, candidate.turn_candidate_id)
            self._resume_source(key.source)
            return False
        return (
            candidate.revision == evidence.candidate_revision
            and self._runtime.participants.source_is_current(key.source)
            and not self._speech_active(candidate)
        )

    @staticmethod
    def _operational_result(
        evidence: TurnTakingEvidence, *, action: TurnTakingAction, reason: str
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

    def _cancel_assessment(self, key: SpeakerKey) -> None:
        task = self._assessment_tasks.get(key)
        if task is asyncio.current_task():
            return
        self._assessment_tasks.pop(key, None)
        if task is not None and not task.done() and not task.cancelling():
            task.cancel()

    def _drop_candidate(self, key: SpeakerKey, *, resume: bool = True) -> None:
        candidate = self._candidates.pop(key, None)
        if candidate is None:
            return

        self._cancel_assessment(key)
        self._cancel_transcript_timer(candidate)
        self._runtime.perception.input_trace.record(
            "candidate.retired",
            candidate_id=candidate.turn_candidate_id,
            candidate_revision=candidate.revision,
            evidence_count=len(candidate.input_observation_ids),
            missing_count=len(candidate.missing_transcripts),
        )

        for segment in candidate.segments:
            if self._segment_owners.get(segment) == key:
                self._segment_owners.pop(segment, None)
            self._retire_segment(segment)
        if resume:
            self._resume_source(key.source)

    def _retire_segment(self, segment: PerceptionSegmentRef) -> None:
        self._retired_segments[segment] = None
        if len(self._retired_segments) > self._MAX_RETIRED_SEGMENTS:
            self._retired_segments.pop(next(iter(self._retired_segments)))
        self._orphan_transcripts.pop(segment, None)
        self._addressing.take_segment(segment)

    @staticmethod
    def _cancel_transcript_timer(candidate: TurnCandidate) -> None:
        if candidate.transcript_timer is not None:
            candidate.transcript_timer.cancel()
            candidate.transcript_timer = None

    def _wait_for_transcript(
        self,
        key: SpeakerKey,
        evidence: TurnTakingEvidence,
        *,
        reason: str,
        commit: TurnTakingDecision | None = None,
    ) -> None:
        if not self._is_current(key, evidence):
            return

        candidate = self._candidates[key]
        if not candidate.pending_transcripts:
            return
        if not self._pending_is_current(candidate):
            self._drop_candidate(key)
            return

        self._publish_result(
            candidate,
            self._operational_result(evidence, action=TurnTakingAction.HOLD, reason=reason),
        )
        # A closed candidate waiting for STT keeps its original segments. New speech for
        # this speaker can now own a separate candidate without stealing their finals.
        if key.segment_id is None:
            pending = replace(key, segment_id=candidate.segments[0].segment_id)
            self._candidates.pop(key)
            self._candidates[pending] = candidate
            candidate.key = pending
            for segment in candidate.segments:
                self._segment_owners[segment] = pending

        loop = asyncio.get_running_loop()
        candidate.transcript_deadline = loop.time() + self._transcript_timeout_sec
        candidate.transcript_commit = commit
        candidate.transcript_owners = {
            segment: IdentityRef.from_participant(owner)
            for segment in candidate.segments
            if (owner := self._runtime.participants.resolve(segment=segment)) is not None
            and owner.user_id is not None
        }
        delay = min(self._transcript_wait_sec, self._transcript_timeout_sec)
        candidate.transcript_timer = loop.call_later(
            delay, self._transcript_wait_elapsed, candidate
        )

    def _transcript_wait_elapsed(self, candidate: TurnCandidate) -> None:
        loop = asyncio.get_running_loop()
        deadline = candidate.transcript_deadline
        if deadline is None or self._candidates.get(candidate.key) is not candidate:
            return
        if not self._pending_is_current(candidate):
            self._drop_candidate(candidate.key)
            return
        if loop.time() < deadline:
            self._runtime.perception.input_trace.record(
                "candidate.transcript_wait",
                candidate_id=candidate.turn_candidate_id,
                candidate_revision=candidate.revision,
                outcome="pending",
                missing_count=len(candidate.pending_transcripts),
            )
            candidate.transcript_timer = loop.call_at(
                deadline, self._transcript_wait_elapsed, candidate
            )
            return
        self._expire_transcript_wait(candidate)

    def _expire_transcript_wait(self, candidate: TurnCandidate) -> None:
        candidate.unavailable_transcripts.update(
            dict.fromkeys(candidate.pending_transcripts, self._transcript_timeout_notice_code)
        )
        self._finish_transcript_wait(candidate, reason="transcript_timeout")

    def _finish_transcript_wait(self, candidate: TurnCandidate, *, reason: str) -> None:
        key = candidate.key
        if self._candidates.get(key) is not candidate:
            return
        if self._pending_is_current(candidate):
            evidence = self._builder.build(candidate)
            result = self._resolve_timeout(candidate, evidence, reason)
            if not candidate.transcripts and result.decision.action != TurnTakingAction.COMMIT:
                result = self._operational_result(
                    evidence, action=TurnTakingAction.CANCEL, reason=reason
                )
            self._publish_result(candidate, result)
        self._drop_candidate(key)

    def _with_transcript_notice(
        self, candidate: TurnCandidate, result: TurnTakingPolicyResult
    ) -> TurnTakingPolicyResult:
        decision = result.decision
        reason = (
            "transcript_timeout"
            if decision.reason == "transcript_timeout"
            else "transcript_unavailable"
        )
        codes = candidate.unavailable_transcripts
        code = next((codes[segment] for segment in candidate.segments if codes.get(segment)), None)
        if not candidate.transcripts and (
            code is None
            or candidate.speech_order != self._speech_order
            or self._runtime.perception.has_active_speech
            or not any(ref.kind == InteractionEntityKind.AVATAR for ref in decision.addressees)
        ):
            return self._operational_result(
                self._builder.build(candidate), action=TurnTakingAction.CANCEL, reason=reason
            )
        if code is None:
            return result

        failed = tuple(
            segment.segment_id for segment in candidate.segments if codes.get(segment) == code
        )
        return replace(
            result,
            decision=replace(
                decision, reason=reason, system_notice_code=code, system_notice_segment_ids=failed
            ),
        )

    def _pending_is_current(self, candidate: TurnCandidate) -> bool:
        source = candidate.key.source
        return (
            not candidate.has_entity_conflict
            and candidate.context_id == self._runtime.state.context_id
            and self._runtime.participants.source_is_current(source)
            and self._runtime.perception.speech_source_is_current(source)
            and all(
                owner.matches(self._runtime.participants.resolve(segment=segment))
                for segment, owner in candidate.transcript_owners.items()
            )
        )

    async def _hold_then_resolve(
        self, key: SpeakerKey, evidence: TurnTakingEvidence, *, timeout_sec: float, reason: str
    ) -> None:
        await asyncio.sleep(timeout_sec)

        if not self._is_current(key, evidence):
            return

        candidate = self._candidates[key]
        await self._settle_assessment(
            key,
            evidence,
            self._resolve_timeout(candidate, evidence, reason),
            transcript_reason="awaiting_transcript_after_turn_timeout",
        )

    def _resolve_timeout(
        self, candidate: TurnCandidate, evidence: TurnTakingEvidence, reason: str
    ) -> TurnTakingPolicyResult:
        return self._policy.resolve_timeout(
            evidence=evidence, addressing=self._addressing.resolve(candidate), reason=reason
        )

    async def _settle_assessment(
        self,
        key: SpeakerKey,
        evidence: TurnTakingEvidence,
        result: TurnTakingPolicyResult,
        *,
        transcript_reason: str,
    ) -> None:
        candidate = self._candidates[key]
        action = result.decision.action
        if action == TurnTakingAction.COMMIT:
            if candidate.pending_transcripts:
                self._wait_for_transcript(
                    key, evidence, reason=transcript_reason, commit=result.decision
                )
                return
            if not await self._prepare_commit(key, evidence):
                return

        self._publish_result(candidate, result)
        if action in self._TERMINAL_ACTIONS:
            self._drop_candidate(key)

    async def _prepare_commit(self, key: SpeakerKey, evidence: TurnTakingEvidence) -> bool:
        if not self._is_current(key, evidence):
            return False

        candidate = self._candidates[key]
        if candidate.association_deadline is None:
            # Reassessment and late transcripts share one budget for this candidate.
            candidate.association_deadline = (
                asyncio.get_running_loop().time() + self._association_wait_sec
            )
        started_at = self._runtime.clock.now()
        outcome = "ready"
        try:
            async with asyncio.timeout_at(candidate.association_deadline):
                await self._runtime.participants.wait_for_segments(tuple(candidate.segments))
        except TimeoutError:
            outcome = "timeout"

        self._runtime.perception.input_trace.record(
            "candidate.association",
            candidate_id=candidate.turn_candidate_id,
            candidate_revision=evidence.candidate_revision,
            outcome=outcome,
            start_time_ns=started_at.monotonic_ns,
            end_time_ns=self._runtime.clock.now().monotonic_ns,
            evidence_count=len(candidate.segments),
            missing_count=sum(
                self._runtime.participants.entity_for_segment(segment) is None
                for segment in candidate.segments
            ),
        )

        # A successful association changes the evidence and schedules a fresh assessment.
        return self._is_current(key, evidence)

    async def _assess_candidate(self, key: SpeakerKey, turn_candidate_id: str) -> None:
        try:
            candidate = self._candidate(key, turn_candidate_id)
            if candidate is None or self._speech_active(candidate):
                return
            if candidate.transcript_deadline is not None and not self._pending_is_current(
                candidate
            ):
                self._drop_candidate(key)
                return

            if self._refresh_speaker(candidate):
                self._resume_source(key.source)
            evidence = self._builder.build(candidate)

            if (commit := candidate.transcript_commit) is not None:
                # The endpoint was settled before STT caught up. Keep that boundary and
                # recheck the evidence available at commit without another endpoint wait.
                evidence = replace(evidence, turn_mode=commit.turn_mode)
                if not await self._prepare_commit(key, evidence):
                    return
                result = self._resolve_timeout(
                    candidate, evidence, commit.reason or "transcript_ready"
                )
                if result.decision.action == TurnTakingAction.COMMIT:
                    result = replace(
                        result, decision=replace(result.decision, confidence=commit.confidence)
                    )
                self._publish_result(candidate, result)
                self._drop_candidate(key)
                return

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

            if self._model.capabilities.uses_transcript:
                if candidate.pending_transcripts:
                    self._wait_for_transcript(
                        key, evidence, reason="awaiting_transcript_for_assessment"
                    )
                    return
                if candidate.unavailable_transcripts and not candidate.transcripts:
                    self._finish_transcript_wait(candidate, reason="transcript_unavailable")
                    return

            try:
                assessment = await self._model.assess(evidence)
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._is_current(key, evidence):
                    return

                logger.exception(
                    "Turn assessment failed turn_candidate_id=%s model=%s",
                    evidence.turn_candidate_id,
                    self._model.name,
                )
                self._publish_result(
                    candidate,
                    self._operational_result(
                        evidence, action=TurnTakingAction.HOLD, reason="turn_assessment_error"
                    ),
                )
                await self._hold_then_resolve(
                    key, evidence, timeout_sec=self._max_hold_sec, reason="assessment_error_timeout"
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
            if not self._addressing.ready(candidate):
                self._publish_result(
                    candidate,
                    self._operational_result(
                        evidence, action=TurnTakingAction.HOLD, reason="awaiting_addressing"
                    ),
                )

                await asyncio.sleep(self._addressing_wait_sec)
                if not self._is_current(key, evidence):
                    return

                candidate = self._candidates[key]
                if not self._addressing.ready(candidate):
                    await self._settle_assessment(
                        key,
                        evidence,
                        self._resolve_timeout(candidate, evidence, "addressing_timeout"),
                        transcript_reason="awaiting_transcript_after_addressing_timeout",
                    )
                    return

            assessment = self._addressing.apply(assessment, candidate)
            result = self._policy.decide(evidence=evidence, assessment=assessment)

            await self._settle_assessment(
                key, evidence, result, transcript_reason="awaiting_transcript_for_commit"
            )

            if result.decision.action == TurnTakingAction.HOLD:
                waiting_for_addressing = result.decision.reason == "addressing_unknown"

                await self._hold_then_resolve(
                    key,
                    evidence,
                    timeout_sec=(
                        self._addressing_wait_sec if waiting_for_addressing else self._max_hold_sec
                    ),
                    reason=(
                        "addressing_timeout" if waiting_for_addressing else "turn_hold_timeout"
                    ),
                )

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Turn assessment task failed turn_candidate_id=%s", turn_candidate_id)
        finally:
            if self._assessment_tasks.get(key) is asyncio.current_task():
                self._assessment_tasks.pop(key, None)

    def _schedule_assessment(self, key: SpeakerKey, turn_candidate_id: str) -> None:
        self._cancel_assessment(key)
        candidate = self._candidate(key, turn_candidate_id)
        if (
            candidate is None
            or not candidate.closed_segments
            or key.source in self._cancelled_sources
            or not self._runtime.participants.source_is_current(key.source)
            or self._speech_active(candidate)
            or (candidate.transcript_deadline is not None and candidate.pending_transcripts)
        ):
            return

        task = asyncio.create_task(
            self._assess_candidate(key, turn_candidate_id),
            name=f"router_turn_assessment:{turn_candidate_id}",
        )
        self._assessment_tasks[key] = task
        self._assessment_workers.add(task)
        task.add_done_callback(self._assessment_workers.discard)

    """Addressing Helper"""

    def _maybe_interrupt(self, candidate: TurnCandidate, observation_id: str) -> None:
        if candidate.interruption_requested:
            return

        evidence = self._builder.build(candidate)
        result = self._policy.decide_interruption(
            evidence=evidence, addressing=self._addressing.resolve(candidate)
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
        self, key: SpeakerKey, candidate: TurnCandidate, record: AddressingEvidenceRecord
    ) -> None:
        observation = self._runtime.perception.timeline.get_observation(
            observation_id=record.target_observation_id
        )
        changed = self._refresh_speaker(candidate, observation)
        if not self._addressing.matches_speaker(candidate, record):
            logger.warning(
                "Addressing evidence speaker mismatch turn_candidate_id=%s annotation_id=%s",
                candidate.turn_candidate_id,
                record.annotation_id,
            )
        elif self._addressing.update(candidate, record, speaker_changed=changed):
            self._cancel_assessment(key)
            if candidate.active_segments:
                self._maybe_interrupt(candidate, record.target_observation_id)
            else:
                self._schedule_assessment(key, candidate.turn_candidate_id)
        if changed:
            self._resume_source(key.source)

    def _route_addressing(self, record: AddressingEvidenceRecord) -> None:
        segment = record.target_segment
        if segment is None:
            match = self._addressing.match_unsegmented(record, self._candidates)
            if match is None:
                self._addressing.defer_unsegmented(record)
            else:
                self._apply_addressing(*match, record)
        elif (
            segment not in self._retired_segments and segment.source not in self._cancelled_sources
        ):
            key = self._segment_owners.get(segment)
            if key is None:
                self._addressing.defer_segment(segment, record)
            elif (candidate := self._candidates.get(key)) is not None:
                self._apply_addressing(key, candidate, record)

    """Observation Handler"""

    def _trace_segment(
        self,
        stage: str,
        segment: PerceptionSegmentRef,
        observation: EnvObservation,
        *,
        candidate: TurnCandidate | None = None,
        state: str | None = None,
        reason: str | None = None,
    ) -> None:
        self._runtime.perception.input_trace.record(
            stage,
            source_id=segment.source.source_id,
            source_generation=segment.source.source_generation,
            segment_id=segment.segment_id,
            observation_id=observation.observation_id,
            candidate_id=candidate.turn_candidate_id if candidate is not None else None,
            candidate_revision=candidate.revision if candidate is not None else None,
            state=state,
            reason=reason,
        )

    def _get_candidate(self, observation: EnvObservation) -> tuple[SpeakerKey, TurnCandidate]:
        owner = self._segment_owners.get(observation.segment) if observation.segment else None
        key = owner if owner is not None else SpeakerKey.from_observation(observation)
        candidate = self._candidates.get(key)

        if candidate is None:
            if len(self._candidates) >= self._max_active_candidates:
                oldest_key = next(iter(self._candidates))
                oldest = self._candidates[oldest_key]
                self._publish_result(
                    oldest,
                    self._operational_result(
                        self._builder.build(oldest),
                        action=TurnTakingAction.CANCEL,
                        reason="candidate_capacity",
                    ),
                    observation_id=oldest.latest_observation_id,
                )
                self._drop_candidate(oldest_key)

            candidate = TurnCandidate.create(observation, context_id=self._runtime.state.context_id)
            self._candidates[key] = candidate

        candidate.latest_observation_id = observation.observation_id
        return key, candidate

    def _apply_transcript(
        self,
        key: SpeakerKey,
        candidate: TurnCandidate,
        segment: PerceptionSegmentRef,
        observation: EnvObservation,
    ) -> None:
        changed = self._refresh_speaker(candidate, observation)
        text = self._builder.text(observation)
        if text is None or not candidate.add_transcript(segment, observation, text):
            if changed:
                self._resume_source(segment.source)
            return

        self._trace_segment(
            "candidate.transcript", segment, observation, candidate=candidate, state="accepted"
        )
        if not candidate.pending_transcripts:
            self._cancel_transcript_timer(candidate)

        logger.debug(
            "TURN TRANSCRIPT candidate_id=%s revision=%s segment_id=%s source=%s "
            "generation=%s observation_id=%s chars=%d active_segments=%d",
            candidate.turn_candidate_id,
            candidate.revision,
            segment.segment_id,
            segment.source.source_id,
            segment.source.source_generation,
            observation.observation_id,
            len(text),
            len(candidate.active_segments),
        )
        if not candidate.active_segments:
            self._schedule_assessment(key, candidate.turn_candidate_id)
        if changed:
            self._resume_source(segment.source)

    def _store_orphan_transcript(
        self, segment: PerceptionSegmentRef, observation: EnvObservation
    ) -> None:
        previous = self._orphan_transcripts.get(segment)
        if previous is not None and previous.kind == ObservationKind.TRANSCRIPT_UNAVAILABLE:
            return

        if (
            segment not in self._orphan_transcripts
            and len(self._orphan_transcripts) >= self._MAX_ORPHANS
        ):
            self._orphan_transcripts.pop(next(iter(self._orphan_transcripts)))

        self._orphan_transcripts[segment] = observation

    def _consume_speech(self, observation: EnvObservation) -> None:
        segment = self._builder.require_segment(observation)
        if not self._segment_is_live(segment):
            if observation.kind == ObservationKind.SPEECH_SEGMENT:
                self._trace_segment(
                    "candidate.segment_rejected", segment, observation, reason="retired_segment"
                )
            return

        if (
            observation.kind == ObservationKind.SPEECH_FRAME
            and segment not in self._segment_owners
            and (
                observation.metadata.get("speech_event") != "start"
                or observation.metadata.get("route_index") != 1
            )
        ):
            self._retire_segment(segment)
            self._trace_segment(
                "candidate.segment_rejected", segment, observation, reason="missing_segment_start"
            )
            return

        self._runtime.participants.observe_segment(segment)
        key, candidate = self._get_candidate(observation)
        changed = self._refresh_speaker(candidate, observation)
        if (
            observation.kind == ObservationKind.SPEECH_FRAME
            and segment in candidate.closed_segments
        ):
            if changed:
                self._resume_source(segment.source)
            return

        is_new_segment = candidate.start_segment(segment, observation)
        self._segment_owners[segment] = key
        if is_new_segment:
            self._speech_order += 1
            candidate.speech_order = self._speech_order
            changed = self._refresh_speaker(candidate, observation) or changed
            # SPEECH_FRAME is ephemeral. close_segment/add_transcript attach retained evidence;
            # the frame may still anchor immediate interruption, never a committed Turn.
            self._trace_segment(
                "candidate.segment", segment, observation, candidate=candidate, state="open"
            )

        if is_new_segment or changed:
            for other_key, other in self._candidates.items():
                if other.transcript_deadline is None and self._related_speech(candidate, other):
                    self._cancel_assessment(other_key)

        for record in self._addressing.take_segment(segment):
            self._apply_addressing(key, candidate, record)

        if is_new_segment:
            for record in self._addressing.take_unsegmented():
                self._route_addressing(record)
            self._maybe_interrupt(candidate, observation.observation_id)

        orphan = self._orphan_transcripts.pop(segment, None)
        if orphan is not None:
            self._consume_transcript(orphan)

        if observation.kind != ObservationKind.SPEECH_SEGMENT:
            if changed:
                self._resume_source(segment.source)
            return

        candidate.close_segment(segment, observation)
        self._trace_segment(
            "candidate.segment", segment, observation, candidate=candidate, state="closed"
        )
        logger.debug(
            "TURN SEGMENT CLOSED candidate_id=%s revision=%s segment_id=%s source=%s "
            "generation=%s observation_id=%s active_segments=%d",
            candidate.turn_candidate_id,
            candidate.revision,
            segment.segment_id,
            segment.source.source_id,
            segment.source.source_generation,
            observation.observation_id,
            len(candidate.active_segments),
        )

        audio = self._builder.audio(observation)
        if audio is not None:
            candidate.add_audio(audio)

        if not candidate.active_segments:
            self._schedule_assessment(key, candidate.turn_candidate_id)
        self._resume_source(segment.source)

    def _segment_is_live(self, segment: PerceptionSegmentRef) -> bool:
        return (
            segment not in self._retired_segments
            and segment.source not in self._cancelled_sources
            and self._runtime.participants.source_is_current(segment.source)
        )

    def _consume_transcript(self, observation: EnvObservation) -> None:
        segment = self._builder.require_segment(observation)
        if not self._segment_is_live(segment):
            self._trace_segment(
                "candidate.transcript_rejected", segment, observation, reason="retired_segment"
            )
            return
        key = self._segment_owners.get(segment)

        if key is None:
            self._store_orphan_transcript(segment, observation)
            self._trace_segment("candidate.transcript_pending", segment, observation)
            return

        candidate = self._candidates.get(key)
        if candidate is None or segment in candidate.unavailable_transcripts:
            return
        if candidate.transcript_deadline is not None:
            if not self._pending_is_current(candidate):
                self._drop_candidate(key)
                return
            if segment not in candidate.pending_transcripts:
                return
            if asyncio.get_running_loop().time() >= candidate.transcript_deadline:
                self._expire_transcript_wait(candidate)
                return
        if observation.kind == ObservationKind.TRANSCRIPT_UNAVAILABLE:
            if segment not in candidate.transcripts:
                code = observation.metadata.get("system_notice_code")
                candidate.unavailable_transcripts[segment] = code
                self._trace_segment(
                    "candidate.transcript",
                    segment,
                    observation,
                    candidate=candidate,
                    state="unavailable",
                    reason=observation.metadata.get("reason_code"),
                )
                if candidate.transcript_deadline is not None and not candidate.pending_transcripts:
                    self._cancel_transcript_timer(candidate)
                    self._schedule_assessment(key, candidate.turn_candidate_id)
            return
        self._apply_transcript(key, candidate, segment, observation)

    def _consume_cancelled(self, observation: EnvObservation) -> None:
        segment = self._builder.require_segment(observation)
        if segment.source in self._cancelled_sources:
            self._retire_segment(segment)
            return

        reason = SpeechCancellationReason(observation.metadata["reason_code"]).value
        self._cancelled_sources[segment.source] = None
        if len(self._cancelled_sources) > self._MAX_CANCELLED_SOURCES:
            self._cancelled_sources.pop(next(iter(self._cancelled_sources)))
        self._trace_segment("candidate.cancelled", segment, observation, reason=reason)

        # Cancellation invalidates the derived source epoch, including pending candidates.
        for key, candidate in tuple(self._candidates.items()):
            if key.source != segment.source:
                continue
            self._cancel_assessment(key)
            candidate.cancel_segment(segment, observation)
            self._trace_segment(
                "candidate.segment",
                segment,
                observation,
                candidate=candidate,
                state="cancelled",
                reason=reason,
            )
            self._publish_result(
                candidate,
                self._operational_result(
                    self._builder.build(candidate), action=TurnTakingAction.CANCEL, reason=reason
                ),
            )
            self._drop_candidate(key)

        self._retire_segment(segment)
        for current in tuple(self._orphan_transcripts):
            if current.source == segment.source:
                self._retire_segment(current)
        for current in self._addressing.deferred_segments(segment.source):
            self._retire_segment(current)

    def handle_observation(self, observation: EnvObservation) -> None:
        if observation.kind == ObservationKind.SPEECH_CANCELLED:
            self._consume_cancelled(observation)
            return

        if observation.kind == ObservationKind.TRANSCRIPT_UNAVAILABLE:
            self._consume_transcript(observation)
            return

        for record in self._addressing.take_observation(observation):
            self._route_addressing(record)

        if observation.kind in {ObservationKind.SPEECH_FRAME, ObservationKind.SPEECH_SEGMENT}:
            self._consume_speech(observation)
        elif observation.kind == ObservationKind.TRANSCRIPT_SEGMENT:
            self._consume_transcript(observation)

    """Annotation Handler"""

    def handle_annotation(self, event: PerceptionEvent) -> None:
        if (record := self._addressing.receive(event)) is not None:
            self._route_addressing(record)

    def handle_annotation_gap(self) -> None:
        self._addressing.clear()

        for key, candidate in tuple(self._candidates.items()):
            if not candidate.mark_annotation_gap():
                continue

            self._cancel_assessment(key)
            if not candidate.active_segments:
                self._schedule_assessment(key, candidate.turn_candidate_id)

    async def reset(self, *, retain_retired: bool = False) -> None:
        tasks = tuple(self._assessment_workers)
        if retain_retired:
            for key in tuple(self._candidates):
                self._drop_candidate(key, resume=False)
        else:
            for candidate in self._candidates.values():
                self._cancel_transcript_timer(candidate)
        self._assessment_tasks.clear()
        self._candidates.clear()
        self._segment_owners.clear()
        if not retain_retired:
            self._retired_segments.clear()
            self._cancelled_sources.clear()
        self._orphan_transcripts.clear()
        self._addressing.clear()

        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._assessment_workers.difference_update(tasks)
