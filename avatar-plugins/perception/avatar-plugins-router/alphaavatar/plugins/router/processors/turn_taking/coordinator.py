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

from alphaavatar.agents.router.enums import AssessmentLabel, InteractionEntityKind, TurnTakingAction
from alphaavatar.agents.router.models import TurnTakingModelBase
from alphaavatar.agents.router.schemas import (
    TurnTakingAssessment,
    TurnTakingDecision,
    TurnTakingEvidence,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import PerceptionSegmentRef, PerceptionSourceRef
from alphaavatar.core.perception.schemas import PerceptionEvent
from alphaavatar.core.turn.schemas import TurnNotice, TurnSnapshot

from .addressing import TurnAddressing
from .assessment import AssessmentWork
from .config import TurnTakingConfig
from .evidence import TurnEvidenceBuilder
from .fusion import AddressingFusion
from .policy import TurnTakingPolicy, TurnTakingPolicyResult
from .schemas.state import AddressingEvidenceRecord, InputWindow, TranscriptWait

logger = logging.getLogger(__name__)


class TurnTakingCoordinator:
    """Decide a temporal input window; participant identity belongs to perception consumers."""

    SOURCE = "router.turn_taking"

    _MAX_RETIRED = 256
    _MAX_ORPHANS = 64

    _TERMINAL = frozenset(
        {TurnTakingAction.CANCEL, TurnTakingAction.PASSIVE, TurnTakingAction.PROACTIVE_CHECK}
    )

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        model: TurnTakingModelBase,
        policy: TurnTakingPolicy,
        fusion: AddressingFusion,
        config: TurnTakingConfig,
        transcript_timeout_notice_code: str | None = None,
        required_addressing_sources: tuple[str, ...] = (),
    ) -> None:
        self._runtime = runtime
        self._model = model
        self._policy = policy
        self._config = config
        self._notice_code = transcript_timeout_notice_code

        self._addressing = TurnAddressing(
            runtime=runtime,
            fusion=fusion,
            alignment_sec=config.unsegmented_alignment_sec,
            required_sources=required_addressing_sources,
        )
        self._builder = TurnEvidenceBuilder(runtime)
        self._work = AssessmentWork(runtime)

        self._current: InputWindow | None = None
        self._sealed: dict[str, InputWindow] = {}
        self._segments: dict[PerceptionSegmentRef, InputWindow] = {}
        self._retired: dict[PerceptionSegmentRef, None] = {}
        self._cancelled: dict[PerceptionSourceRef, None] = {}
        self._orphans: dict[PerceptionSegmentRef, EnvObservation] = {}
        self._committed_start = 0

    @property
    def _windows(self) -> tuple[InputWindow, ...]:
        return ((self._current,) if self._current is not None else ()) + tuple(
            self._sealed.values()
        )

    @staticmethod
    def _operational(
        evidence: TurnTakingEvidence, action: TurnTakingAction, reason: str
    ) -> TurnTakingPolicyResult:
        return TurnTakingPolicyResult(
            decision=TurnTakingDecision(
                input_id=evidence.input_id,
                revision=evidence.revision,
                turn_mode=evidence.turn_mode,
                action=action,
                confidence=0.0 if action == TurnTakingAction.HOLD else 1.0,
                actors=evidence.actors,
                input_observation_ids=evidence.input_observation_ids,
                reason=reason,
            )
        )

    """Trace operations"""

    def _trace(self, stage: str, window: InputWindow | None = None, **fields: object) -> None:
        self._runtime.perception.input_trace.record(
            stage,
            input_id=window.input_id if window else None,
            revision=window.revision if window else None,
            **fields,
        )

    def _trace_segment(
        self,
        stage: str,
        segment: PerceptionSegmentRef,
        observation: EnvObservation,
        window: InputWindow | None = None,
        **fields: object,
    ) -> None:
        self._trace(
            stage,
            window,
            source_id=segment.source.source_id,
            source_generation=segment.source.source_generation,
            segment_id=segment.segment_id,
            observation_id=observation.observation_id,
            **fields,
        )

    """Input evidence operations"""

    def _live(self, window: InputWindow) -> bool:
        return (
            (self._current is window or self._sealed.get(window.input_id) is window)
            and window.context_id == self._runtime.state.context_id
            and all(
                self._runtime.perception.speech_source_is_current(source)
                for source in window.sources
            )
            and not any(source in self._cancelled for source in window.sources)
        )

    def _matches(self, window: InputWindow, evidence: TurnTakingEvidence) -> bool:
        return (
            self._live(window)
            and self._work.owns(window.input_id)
            and not window.published
            and window.revision == evidence.revision
            and not window.active_segments
        )

    def _evidence(self, window: InputWindow) -> TurnTakingEvidence:
        # Input membership stays sealed while its audio remains temporal context until admission.
        context = tuple(
            audio for other in self._windows if self._live(other) for audio in other.audio.values()
        )
        return self._builder.build(window, audio=context)

    """Input window operations"""

    def _retire_segment(self, segment: PerceptionSegmentRef) -> None:
        self._segments.pop(segment, None)
        self._orphans.pop(segment, None)
        self._addressing.take_segment(segment)
        self._retired[segment] = None
        if len(self._retired) > self._MAX_RETIRED:
            self._retired.pop(next(iter(self._retired)))

    def _drop(self, window: InputWindow, *, invalidate_context: bool = True) -> None:
        if self._current is not window and self._sealed.get(window.input_id) is not window:
            return
        self._work.cancel(window.input_id)
        if window.wait is not None:
            window.wait.cancel_timer()
        if window.admission_timer is not None:
            window.admission_timer.cancel()
            window.admission_timer = None
        if self._current is window:
            self._current = None
        self._sealed.pop(window.input_id, None)
        for segment in window.segments:
            self._retire_segment(segment)
        self._trace("input.retired", window, evidence_count=len(window.input_observation_ids))
        if invalidate_context and self._current is not None:
            self._context_changed()

    def _window_for(self, observation: EnvObservation) -> InputWindow:
        if observation.segment in self._segments:
            return self._segments[observation.segment]
        if self._current is not None and not self._live(self._current):
            self._drop(self._current)
        if self._current is None:
            self._current = InputWindow(
                context_id=self._runtime.state.context_id,
                started_at=observation.time_range.start,
                updated_at=observation.time_range.end,
            )
        return self._current

    def _seal(self, window: InputWindow) -> None:
        if window.sealed:
            return

        window.sealed = True
        if self._current is window:
            self._current = None

        while len(self._sealed) >= self._config.max_pending_inputs:
            old = next(iter(self._sealed.values()))
            self._publish(
                old,
                self._operational(self._evidence(old), TurnTakingAction.CANCEL, "pending_capacity"),
            )
            self._drop(old)

        self._sealed[window.input_id] = window

    """Decision operations"""

    def _notice(
        self, window: InputWindow, result: TurnTakingPolicyResult
    ) -> TurnTakingPolicyResult:
        decision = result.decision
        if window.wait is not None and window.observed_sequence < self._committed_start:
            return self._operational(
                self._evidence(window), TurnTakingAction.CANCEL, "superseded_transcript"
            )

        codes = window.unavailable_transcripts
        code = next((codes[s] for s in window.segments if codes.get(s)), None)
        if not window.transcripts and (
            code is None
            or self._runtime.perception.has_active_speech
            or not (
                any(ref.kind == InteractionEntityKind.AVATAR for ref in decision.addressees)
                or any(n.code == "router.addressing_uncertain" for n in decision.system_notices)
            )
        ):
            return self._operational(
                self._evidence(window),
                TurnTakingAction.CANCEL,
                window.transcript_failure or decision.reason or "transcript_unavailable",
            )

        notices = tuple(
            TurnNotice(value, tuple(s.segment_id for s in window.segments if codes.get(s) == value))
            for value in dict.fromkeys(codes[s] for s in window.segments if codes.get(s))
        )
        return replace(
            result,
            decision=replace(
                decision,
                reason=window.transcript_failure or "transcript_unavailable",
                system_notices=(*decision.system_notices, *notices),
            ),
        )

    def _admission_elapsed(self, window: InputWindow) -> None:
        if self._sealed.get(window.input_id) is window and window.published:
            self._trace("input.admission_expired", window)
            self._drop(window)

    def _publish(
        self,
        window: InputWindow,
        result: TurnTakingPolicyResult,
        *,
        observation_id: str | None = None,
    ) -> None:
        decision = result.decision
        target = observation_id or window.anchor_observation_id
        if (
            (self._current is not window and self._sealed.get(window.input_id) is not window)
            or window.context_id != self._runtime.state.context_id
            or (decision.action != TurnTakingAction.CANCEL and not self._live(window))
            or window.published
            or decision.revision != window.revision
            or target is None
        ):
            return

        if decision.action == TurnTakingAction.COMMIT:
            if window.wait is not None and window.observed_sequence < self._committed_start:
                result = self._operational(
                    self._evidence(window), TurnTakingAction.CANCEL, "superseded_transcript"
                )
            elif window.unavailable_transcripts:
                result = self._notice(window, result)
            decision = result.decision

        # Freeze membership before publishing: annotation renderers may re-enter the runtime.
        if decision.action == TurnTakingAction.COMMIT:
            self._seal(window)
            window.published = True
            if window.wait is not None:
                window.wait.cancel_timer()

        if result.addressing is not None:
            self._runtime.perception.publish_annotation(
                result.addressing.to_annotation(source=self.SOURCE, observation_id=target)
            )

        annotation = decision.to_annotation(source=self.SOURCE, observation_id=target)
        deadline = self._runtime.clock.now().monotonic_ns + round(
            self._config.commit_timeout_sec * 1e9
        )
        annotation = replace(
            annotation,
            data={
                **annotation.data,
                "context_id": window.context_id,
                "admission_deadline_ns": deadline,
            },
        )
        event = self._runtime.perception.publish_annotation(annotation)
        self._trace(
            "input.decision",
            window,
            decision_id=annotation.annotation_id,
            observation_id=target,
            event_id=event.event_id if event else None,
            sequence=event.sequence if event else None,
            action=decision.action.value,
            outcome="published" if event else "not_published",
            evidence_count=len(decision.input_observation_ids),
            missing_count=len(window.missing_transcripts),
        )
        if decision.action in self._TERMINAL or event is None:
            self._drop(window)
        elif decision.action == TurnTakingAction.COMMIT:
            window.admission_timer = asyncio.get_running_loop().call_later(
                self._config.commit_timeout_sec, self._admission_elapsed, window
            )

    """Transcript wait operations"""

    def _transcript_elapsed(self, window: InputWindow) -> None:
        wait = window.wait
        if wait is None or window.published:
            return
        if not self._live(window):
            self._drop(window)
            return
        loop = asyncio.get_running_loop()
        if loop.time() < wait.deadline:
            self._trace(
                "input.transcript_wait",
                window,
                outcome="pending",
                missing_count=len(window.pending_transcripts),
            )
            wait.timer = loop.call_at(wait.deadline, self._transcript_elapsed, window)
            return
        for segment in window.pending_transcripts.intersection(wait.segments):
            window.unavailable_transcripts[segment] = self._notice_code

        window.revision += 1
        window.transcript_failure = "transcript_timeout"
        wait.cancel_timer()
        if wait.decision is None:
            # A transcript-dependent model has not closed this input. Later speech retains
            # its own budget and remains in the current window, even while it is active.
            window.wait = None
            self._schedule(window)
            return

        # Restore the saved completion judgment, then apply the current addressing.
        # Neither a transcript deadline nor a late final can turn a clear HOLD into COMMIT.
        self._schedule(window)

    def _wait_transcript(
        self, window: InputWindow, decision: TurnTakingDecision | None, reason: str
    ) -> None:
        if window.wait is None:
            loop = asyncio.get_running_loop()
            window.wait = TranscriptWait(
                loop.time() + self._config.transcript_timeout_sec,
                decision,
                frozenset(window.pending_transcripts),
            )
            window.wait.timer = loop.call_later(
                min(self._config.transcript_wait_sec, self._config.transcript_timeout_sec),
                self._transcript_elapsed,
                window,
            )
        elif decision is not None:
            window.wait.decision = decision
        if decision is not None:
            self._seal(window)
        self._publish(
            window, self._operational(self._evidence(window), TurnTakingAction.HOLD, reason)
        )

    """Assessment operations"""

    def _settle(self, window: InputWindow, result: TurnTakingPolicyResult) -> None:
        if result.decision.action == TurnTakingAction.COMMIT and window.pending_transcripts:
            self._wait_transcript(window, result.decision, "awaiting_transcript_for_commit")
        else:
            self._publish(window, result)

    def _decision(
        self, window: InputWindow, evidence: TurnTakingEvidence, assessment: TurnTakingAssessment
    ) -> TurnTakingPolicyResult:
        now = asyncio.get_running_loop().time()
        return self._policy.decide(
            evidence=evidence,
            assessment=assessment,
            speech_completion_expired=window.speech_completion_deadline is not None
            and now >= window.speech_completion_deadline,
            addressing_expired=window.addressing_deadline is not None
            and now >= window.addressing_deadline,
        )

    async def _hold(
        self, window: InputWindow, evidence: TurnTakingEvidence, assessment: TurnTakingAssessment
    ) -> None:
        now = asyncio.get_running_loop().time()
        deadlines = []
        if assessment.speech_completion == AssessmentLabel.UNKNOWN:
            if window.speech_completion_deadline is None:
                window.speech_completion_deadline = now + self._config.speech_completion_wait_sec
            deadlines.append(window.speech_completion_deadline)

        if assessment.addressing == AssessmentLabel.UNKNOWN:
            if window.addressing_deadline is None:
                window.addressing_deadline = now + self._config.addressing_wait_sec
            deadlines.append(window.addressing_deadline)

        if not deadlines:
            return

        deadline = max(deadlines)
        with self._work.span("input.hold", evidence, reason="awaiting_uncertain_decision"):
            while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
                await asyncio.sleep(remaining)

        if self._matches(window, evidence):
            self._settle(window, self._decision(window, evidence, assessment))

    async def _assess(self, window: InputWindow, queued_ns: int) -> None:
        evidence = self._evidence(window)
        if not self._matches(window, evidence):
            return
        if not self._model.capabilities.supports(evidence.turn_mode):
            self._publish(
                window,
                self._operational(evidence, TurnTakingAction.CANCEL, "unsupported_turn_mode"),
            )
            return

        saved = window.wait.decision if window.wait is not None else None
        if saved is not None:
            # Completion was already accepted before STT finished. Keep its uncertainty
            # fact, but let the newly available transcript supply fresh addressing.
            uncertain = any(
                n.code == "router.speech_completion_uncertain" for n in saved.system_notices
            )
            assessment = TurnTakingAssessment(
                input_id=evidence.input_id,
                revision=evidence.revision,
                turn_mode=evidence.turn_mode,
                confidence=saved.confidence,
                speech_completion=AssessmentLabel.UNKNOWN
                if uncertain
                else AssessmentLabel.POSITIVE,
            )
        elif self._model.capabilities.uses_transcript and window.pending_transcripts:
            if window.speech_completion_deadline is None:
                window.speech_completion_deadline = (
                    asyncio.get_running_loop().time() + self._config.speech_completion_wait_sec
                )
            self._wait_transcript(window, None, "awaiting_transcript_for_assessment")
            return
        elif self._model.capabilities.uses_transcript and not window.transcripts:
            assessment = TurnTakingAssessment(
                input_id=evidence.input_id,
                revision=evidence.revision,
                turn_mode=evidence.turn_mode,
                confidence=0.0,
                reason="transcript_unavailable",
            )
        else:
            try:
                with self._work.span("input.assessment", evidence, event_time_ns=queued_ns):
                    assessment = await self._model.assess(evidence)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Speech completion assessment failed input_id=%s", window.input_id)
                assessment = TurnTakingAssessment(
                    input_id=evidence.input_id,
                    revision=evidence.revision,
                    turn_mode=evidence.turn_mode,
                    confidence=0.0,
                    reason="speech_completion_failed",
                )
        if not self._matches(window, evidence):
            return

        assessment = self._addressing.apply(assessment, window)
        self._trace("input.speech_completion", window, state=assessment.speech_completion.value)
        if (
            assessment.speech_completion == AssessmentLabel.UNKNOWN
            and window.speech_completion_deadline is None
        ):
            window.speech_completion_deadline = (
                asyncio.get_running_loop().time() + self._config.speech_completion_wait_sec
            )

        result = self._decision(window, evidence, assessment)
        if assessment.speech_completion == AssessmentLabel.NEGATIVE:
            self._settle(window, result)
            return

        # A configured text-based addressee cannot run before its full VAD transcript.
        # Its wait starts when that input is available, independently of STT's deadline.
        if not self._addressing.ready(window) and window.pending_transcripts:
            self._wait_transcript(window, None, "awaiting_transcript_for_addressing")
            return

        if not self._addressing.ready(window):
            assessment = replace(
                assessment,
                addressing=AssessmentLabel.UNKNOWN,
                addressees=(),
                addressing_confidence=None,
            )
            result = self._decision(window, evidence, assessment)

        self._settle(window, result)
        if result.decision.action == TurnTakingAction.HOLD:
            if window.pending_transcripts:
                self._wait_transcript(window, None, "awaiting_transcript_for_decision")
                return

            await self._hold(window, evidence, assessment)

    def _schedule(self, window: InputWindow) -> None:
        self._work.cancel(window.input_id)
        if (
            not self._live(window)
            or window.published
            or window.active_segments
            or not window.closed_segments
        ):
            return

        if window.wait is not None and window.pending_transcripts:
            return

        queued = self._runtime.clock.now().monotonic_ns
        self._work.start(window.input_id, lambda: self._assess(window, queued))

    def _context_changed(self) -> None:
        if self._current is not None:
            self._current.revision += 1
            self._schedule(self._current)

    """Input event operations"""

    def _route_addressing(self, record: AddressingEvidenceRecord) -> None:
        windows = {window.input_id: window for window in self._windows if not window.published}
        match = self._addressing.match_window(record, windows)
        if match is None:
            if record.target_segment is not None and record.target_segment not in self._retired:
                self._addressing.defer_segment(record.target_segment, record)
            elif record.target_segment is None:
                self._addressing.defer_unsegmented(record)
            return

        _, window = match
        if self._addressing.update(window, record):
            self._schedule(window)

    def _consume_transcript(self, observation: EnvObservation) -> None:
        segment = self._builder.require_segment(observation)
        if segment in self._retired or segment.source in self._cancelled:
            self._trace_segment(
                "input.transcript_rejected", segment, observation, reason="retired_segment"
            )
            return

        window = self._segments.get(segment)
        if window is None:
            previous = self._orphans.get(segment)
            if previous is None or previous.kind != ObservationKind.TRANSCRIPT_UNAVAILABLE:
                self._orphans[segment] = observation
                if len(self._orphans) > self._MAX_ORPHANS:
                    self._orphans.pop(next(iter(self._orphans)))
            self._trace_segment("input.transcript_pending", segment, observation)
            return

        if not self._live(window):
            self._drop(window)
            return
        if window.published or segment in window.unavailable_transcripts:
            return

        if window.wait is not None and asyncio.get_running_loop().time() >= window.wait.deadline:
            self._transcript_elapsed(window)
            if (
                not self._live(window)
                or window.published
                or segment in window.unavailable_transcripts
            ):
                return

        if observation.kind == ObservationKind.TRANSCRIPT_UNAVAILABLE:
            if segment not in window.transcripts:
                window.unavailable_transcripts[segment] = observation.metadata.get(
                    "system_notice_code"
                )
                window.revision += 1
                self._trace_segment(
                    "input.transcript",
                    segment,
                    observation,
                    window,
                    state="unavailable",
                    reason=observation.metadata.get("reason_code"),
                )
        else:
            text = self._builder.text(observation)
            if text is None or not window.add_transcript(segment, observation, text):
                return
            self._trace_segment("input.transcript", segment, observation, window, state="final")

        if window.wait is not None and not window.pending_transcripts.intersection(
            window.wait.segments
        ):
            window.wait.cancel_timer()
            if window.wait.decision is None:
                window.wait = None
        self._schedule(window)

    def _consume_speech(self, observation: EnvObservation) -> None:
        segment = self._builder.require_segment(observation)
        if segment in self._retired or segment.source in self._cancelled:
            self._trace_segment(
                "input.segment_rejected", segment, observation, reason="retired_segment"
            )
            return

        if (
            observation.kind == ObservationKind.SPEECH_FRAME
            and segment not in self._segments
            and (
                observation.metadata.get("speech_event") != "start"
                or observation.metadata.get("route_index") != 1
            )
        ):
            self._retire_segment(segment)
            return

        window = self._window_for(observation)
        if window.published or window.sealed:
            return

        if (
            segment not in window.segments
            and len(window.segments) >= self._config.max_window_segments
        ):
            self._publish(
                window,
                self._operational(
                    self._evidence(window), TurnTakingAction.CANCEL, "input_capacity"
                ),
            )
            self._drop(window)
            window = self._window_for(observation)

        added = window.start_segment(segment, observation)
        self._segments[segment] = window
        if added:
            self._work.cancel(window.input_id)
            self._trace_segment("input.segment", segment, observation, window, state="open")
            interruption = self._policy.decide_interruption(
                evidence=self._evidence(window), addressing=self._addressing.resolve(window)
            )
            if interruption is not None and window.claim_interruption():
                self._publish(window, interruption, observation_id=observation.observation_id)

        for record in self._addressing.take_segment(segment):
            self._route_addressing(record)
        for record in self._addressing.take_unsegmented():
            self._route_addressing(record)
        if observation.kind == ObservationKind.SPEECH_SEGMENT and window.close_segment(
            segment, observation
        ):
            if not window.observed_sequence:
                # Use the retained event's sequence, not the stream tail at batch-processing time.
                window.observed_sequence = next(
                    (
                        event.sequence
                        for event in self._runtime.perception.events.read_range(after_seq=0).items
                        if event.observation is not None
                        and event.observation.observation_id == observation.observation_id
                    ),
                    0,
                )
            if (audio := self._builder.audio(observation)) is not None:
                window.add_audio(audio)
            self._trace_segment("input.segment", segment, observation, window, state="closed")
            if (orphan := self._orphans.pop(segment, None)) is not None:
                self._consume_transcript(orphan)
            self._schedule(window)

    def _consume_cancelled(self, observation: EnvObservation) -> None:
        segment = self._builder.require_segment(observation)
        self._cancelled[segment.source] = None
        if len(self._cancelled) > self._MAX_RETIRED:
            self._cancelled.pop(next(iter(self._cancelled)))
        for window in self._windows:
            if segment.source in window.sources:
                self._publish(
                    window,
                    self._operational(
                        self._evidence(window),
                        TurnTakingAction.CANCEL,
                        observation.metadata.get("reason_code", "speech_cancelled"),
                    ),
                    observation_id=observation.observation_id,
                )
                self._drop(window)
        self._retire_segment(segment)
        self._context_changed()

    def handle_observation(self, observation: EnvObservation) -> None:
        for record in self._addressing.take_observation(observation):
            self._route_addressing(record)
        if observation.kind in (ObservationKind.SPEECH_FRAME, ObservationKind.SPEECH_SEGMENT):
            self._consume_speech(observation)
        elif observation.kind in (
            ObservationKind.TRANSCRIPT_SEGMENT,
            ObservationKind.TRANSCRIPT_UNAVAILABLE,
        ):
            self._consume_transcript(observation)
        elif observation.kind == ObservationKind.SPEECH_CANCELLED:
            self._consume_cancelled(observation)

    def handle_annotation(self, event: PerceptionEvent) -> None:
        if (record := self._addressing.receive(event)) is not None:
            self._route_addressing(record)

    def handle_annotation_gap(self) -> None:
        self._addressing.clear()
        for window in self._windows:
            if window.mark_annotation_gap():
                self._schedule(window)

    def handle_turn(self, snapshot: TurnSnapshot) -> None:
        # The acknowledgement is authoritative even if cancellation already removed its
        # local record. Snapshot-owned event references survive overlapping cutoffs.
        owned = set(snapshot.input_observation_ids)
        first = min(
            (
                event.sequence
                for event in snapshot.perception_events
                if event.observation is not None and event.observation.observation_id in owned
            ),
            default=0,
        )
        self._committed_start = max(self._committed_start, first)
        if (window := self._sealed.get(snapshot.input_id)) is not None:
            self._drop(window, invalidate_context=False)

        self._context_changed()

    """Runtime operations"""

    async def reset(self, *, retain_retired: bool = False) -> None:
        for window in self._windows:
            self._drop(window)
        self._orphans.clear()
        self._addressing.clear()
        if not retain_retired:
            self._retired.clear()
            self._cancelled.clear()
        await self._work.reset()
