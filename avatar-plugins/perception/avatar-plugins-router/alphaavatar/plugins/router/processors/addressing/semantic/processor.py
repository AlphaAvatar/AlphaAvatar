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
from collections import OrderedDict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.router.enums import (
    AddressingEvidenceKind,
    AddressingMode,
    InteractionEntityKind,
    SemanticAddressingLabel,
    TurnTakingAction,
)
from alphaavatar.agents.router.schemas import (
    InteractionAddressingEvidence,
    InteractionEntityRef,
    SemanticAddressingRequest,
    SemanticAddressingResult,
    SemanticAddressingTranscript,
    TurnTakingDecision,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import AnnotationKind, ObservationKind
from alphaavatar.core.env.schemas import PerceptionSegmentRef
from alphaavatar.core.media import TextPayload
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.perception.schemas import PerceptionEvent

from .config import SemanticAddressingConfig
from .factory import create_semantic_addressing_model

logger = logging.getLogger(__name__)

SpeakerKey = tuple[str, int, str, str]

_TERMINAL_ACTIONS = {
    TurnTakingAction.COMMIT,
    TurnTakingAction.CANCEL,
    TurnTakingAction.PASSIVE,
    TurnTakingAction.PROACTIVE_CHECK,
}


@dataclass(frozen=True, slots=True)
class _TranscriptRecord:
    segment: PerceptionSegmentRef
    transcript: SemanticAddressingTranscript
    observation_id: str


@dataclass(frozen=True, slots=True)
class _AssessmentJob:
    generation: int
    request: SemanticAddressingRequest
    speaker: InteractionEntityRef
    observation_id: str
    evidence_observation_ids: tuple[str, ...]


@dataclass(slots=True)
class _SpeakerState:
    speaker: InteractionEntityRef
    history: deque[tuple[SemanticAddressingTranscript, ...]]
    current: OrderedDict[PerceptionSegmentRef, _TranscriptRecord] = field(
        default_factory=OrderedDict
    )
    pending: deque[_AssessmentJob] = field(default_factory=deque)
    focus: tuple[SemanticAddressingLabel, float] | None = None
    focus_at_turn_start: str | None = None
    generation: int = 0
    assessing: _AssessmentJob | None = None
    worker: asyncio.Task[None] | None = None


class SemanticAddressingProcessor(RouterProcessorBase):
    OBSERVATION_CONSUMER_ID = "router.addressing.semantic.observations"
    ANNOTATION_CONSUMER_ID = "router.addressing.semantic.annotations"
    SEMANTIC_SOURCE = "router.addressing.semantic"
    FOCUS_SOURCE = "router.addressing.focus"

    def __init__(self, *, runtime: AvatarRuntime, config: SemanticAddressingConfig) -> None:
        super().__init__(runtime=runtime)

        self._model = create_semantic_addressing_model(
            config.model.name, inference_executor=runtime.inference
        )
        self._avatar_identities = config.avatar_identities
        self._history_turns = config.history_turns
        self._states: dict[SpeakerKey, _SpeakerState] = {}
        self._retired_segments: dict[PerceptionSegmentRef, None] = {}
        self._workers: set[asyncio.Task[None]] = set()
        self._tasks: tuple[asyncio.Task[None], ...] = ()
        self._started = False

    @property
    def name(self) -> str:
        return "semantic_addressing"

    @staticmethod
    def _text(observation: EnvObservation) -> str | None:
        payload = observation.payload
        if not isinstance(payload, TextPayload):
            return None
        return payload.text.strip() or None

    @staticmethod
    def _history_segments(state: _SpeakerState) -> tuple[SemanticAddressingTranscript, ...]:
        return tuple(
            SemanticAddressingTranscript(
                text=" ".join(segment.text for segment in turn).strip(), final=True
            )
            for turn in state.history
            if any(segment.text.strip() for segment in turn)
        )

    @staticmethod
    def _target(
        label: SemanticAddressingLabel,
    ) -> tuple[tuple[InteractionEntityRef, ...], AddressingMode]:
        if label == SemanticAddressingLabel.AVATAR:
            return (InteractionEntityRef(kind=InteractionEntityKind.AVATAR),), AddressingMode.DIRECT
        if label == SemanticAddressingLabel.NON_AVATAR:
            return (
                InteractionEntityRef(kind=InteractionEntityKind.UNKNOWN),
            ), AddressingMode.DIRECT
        return (), AddressingMode.UNKNOWN

    @staticmethod
    def _confidence(label: SemanticAddressingLabel, p_avatar: float) -> float:
        if label == SemanticAddressingLabel.AVATAR:
            return p_avatar
        if label == SemanticAddressingLabel.NON_AVATAR:
            return 1.0 - p_avatar
        return 0.0

    @staticmethod
    def _cancel_worker(state: _SpeakerState) -> None:
        worker = state.worker
        state.worker = None
        state.assessing = None
        if worker is not None:
            worker.cancel()

    def _speaker(self, observation: EnvObservation) -> InteractionEntityRef:
        entity = observation.entity
        if entity is None and observation.segment is not None:
            entity = self._runtime.participants.entity_for_segment(observation.segment)

        return InteractionEntityRef(
            kind=InteractionEntityKind.PERSON,
            entity=entity,
            device_id=observation.device_id,
            source=observation.segment.source if observation.segment else observation.source,
        )

    def _key_from_observation(self, observation: EnvObservation) -> SpeakerKey:
        speaker = self._speaker(observation)
        source = observation.segment.source if observation.segment else observation.source
        if speaker.entity is not None:
            return (source.source_id, source.source_generation, "entity", speaker.entity.entity_id)

        if observation.segment is not None:
            return (
                source.source_id,
                source.source_generation,
                "segment",
                observation.segment.segment_id,
            )

        return source.source_id, source.source_generation, "observation", observation.observation_id

    def _state(self, observation: EnvObservation) -> tuple[SpeakerKey, _SpeakerState]:
        key = self._key_from_observation(observation)
        speaker = self._speaker(observation)
        state = self._states.get(key)

        if state is None:
            # Shared endpoints may expose many transient subjects; retain bounded histories.
            if len(self._states) >= 128:
                removed = self._states.pop(next(iter(self._states)))
                removed.generation += 1
                removed.pending.clear()
                self._remember_retired(removed.current)
                self._cancel_worker(removed)

            state = _SpeakerState(speaker=speaker, history=deque(maxlen=self._history_turns))
            self._states[key] = state
        else:
            state.speaker = speaker

        return key, state

    def _request(self, state: _SpeakerState) -> SemanticAddressingRequest:
        current = tuple(record.transcript for record in state.current.values())
        return SemanticAddressingRequest(
            avatar_identities=self._avatar_identities,
            previous_focus=state.focus_at_turn_start,
            transcript_segments=(*self._history_segments(state), *current),
        )

    def _start_worker(self, key: SpeakerKey, state: _SpeakerState) -> None:
        if state.pending and (state.worker is None or state.worker.done()):
            state.worker = asyncio.create_task(
                self._run_jobs(key, state), name=f"router_semantic_addressing:{key[0]}:{key[1]}"
            )
            self._workers.add(state.worker)
            state.worker.add_done_callback(self._workers.discard)

    def _enqueue(self, key: SpeakerKey, state: _SpeakerState, observation_id: str) -> None:
        if len(state.pending) >= 2:
            state.pending.popleft()

        state.pending.append(
            _AssessmentJob(
                generation=state.generation,
                request=self._request(state),
                speaker=state.speaker,
                observation_id=observation_id,
                evidence_observation_ids=tuple(
                    record.observation_id for record in state.current.values()
                ),
            )
        )

        self._start_worker(key, state)

    def _evidence(
        self,
        *,
        kind: AddressingEvidenceKind,
        label: SemanticAddressingLabel,
        confidence: float,
        speaker: InteractionEntityRef,
        observation_ids: tuple[str, ...],
        raw_score: float | None = None,
    ) -> InteractionAddressingEvidence:
        addressees, mode = self._target(label)
        return InteractionAddressingEvidence(
            evidence_kind=kind,
            speaker=speaker,
            addressees=addressees,
            addressing_mode=mode,
            confidence=confidence,
            evidence_label=label.value,
            raw_score=raw_score,
            evidence_observation_ids=observation_ids,
        )

    def _publish(
        self, state: _SpeakerState, job: _AssessmentJob, result: SemanticAddressingResult
    ) -> None:
        confidence = self._confidence(result.label, result.p_avatar)

        semantic = self._evidence(
            kind=AddressingEvidenceKind.SEMANTIC,
            label=result.label,
            confidence=confidence,
            speaker=job.speaker,
            observation_ids=job.evidence_observation_ids,
            raw_score=result.p_avatar,
        )
        self._runtime.perception.publish_annotation(
            semantic.to_annotation(source=self.SEMANTIC_SOURCE, observation_id=job.observation_id)
        )

        if result.label != SemanticAddressingLabel.UNKNOWN:
            state.focus = result.label, confidence
        elif state.focus is not None:
            focus_label, focus_confidence = state.focus
            focus = self._evidence(
                kind=AddressingEvidenceKind.CONVERSATION_FOCUS,
                label=focus_label,
                confidence=focus_confidence,
                speaker=job.speaker,
                observation_ids=job.evidence_observation_ids,
            )
            self._runtime.perception.publish_annotation(
                focus.to_annotation(source=self.FOCUS_SOURCE, observation_id=job.observation_id)
            )

        logger.debug(
            "Semantic Addressing label=%s p_avatar=%.4f focus=%s observation_id=%s",
            result.label.value,
            result.p_avatar,
            state.focus[0].value if state.focus else None,
            job.observation_id,
        )

    async def _run_jobs(self, key: SpeakerKey, state: _SpeakerState) -> None:
        worker = asyncio.current_task()
        try:
            while state.worker is worker and state.pending:
                job = state.pending.popleft()
                state.assessing = job

                try:
                    result = await self._model.assess(job.request)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Semantic Addressing inference failed observation_id=%s model=%s",
                        job.observation_id,
                        self._model.name,
                    )
                else:
                    if (
                        state.worker is worker
                        and state.assessing is job
                        and self._states.get(key) is state
                        and state.generation == job.generation
                        and job.speaker.source is not None
                        and self._runtime.participants.source_is_current(job.speaker.source)
                    ):
                        self._publish(state, job, result)
                finally:
                    if state.worker is worker and state.assessing is job:
                        state.assessing = None

        finally:
            if state.worker is worker:
                state.worker = None
                state.assessing = None

    def _consume_transcript(self, observation: EnvObservation) -> None:
        if observation.kind != ObservationKind.TRANSCRIPT_SEGMENT or observation.segment is None:
            return

        source = observation.segment.source
        if not self._runtime.participants.observe_source(source):
            return

        for key, previous in tuple(self._states.items()):
            if key[0] == source.source_id and key[1] < source.source_generation:
                previous.generation += 1
                previous.pending.clear()
                self._cancel_worker(previous)
                self._states.pop(key, None)

        if observation.segment in self._retired_segments:
            return

        text = self._text(observation)
        if text is None:
            return

        key, state = self._state(observation)
        if not state.current:
            state.focus_at_turn_start = state.focus[0].value if state.focus else None

        transcript = SemanticAddressingTranscript(text=text, final=True)
        previous = state.current.get(observation.segment)
        if previous is not None and previous.transcript == transcript:
            return

        state.current[observation.segment] = _TranscriptRecord(
            segment=observation.segment,
            transcript=transcript,
            observation_id=observation.observation_id,
        )
        self._enqueue(key, state, observation.observation_id)

    def _remember_retired(self, segments: Iterable[PerceptionSegmentRef]) -> None:
        for segment in segments:
            self._retired_segments[segment] = None
        while len(self._retired_segments) > 256:
            self._retired_segments.pop(next(iter(self._retired_segments)))

    def _finish_turn(
        self, decision: TurnTakingDecision, *, observation_id: str | None = None
    ) -> None:
        observation_ids = set(decision.input_observation_ids)
        if observation_id is not None:
            observation_ids.add(observation_id)

        timeline = self._runtime.perception.timeline
        segments = {
            observation.segment
            for observation_id in observation_ids
            if (observation := timeline.get_observation(observation_id=observation_id)) is not None
            and observation.segment is not None
        }
        segments.update(
            record.segment
            for state in self._states.values()
            for record in state.current.values()
            if record.observation_id in observation_ids
        )
        observation_ids.update(
            record.observation_id
            for state in self._states.values()
            for record in state.current.values()
            if record.segment in segments
        )
        self._remember_retired(segments)

        def uses_retired(job: _AssessmentJob) -> bool:
            return any(
                observation_id in observation_ids
                or (
                    (observation := timeline.get_observation(observation_id=observation_id))
                    is not None
                    and observation.segment in segments
                )
                for observation_id in job.evidence_observation_ids
            )

        for key, state in tuple(self._states.items()):
            retired = tuple(
                state.current.pop(segment)
                for segment in tuple(state.current)
                if segment in segments
            )
            pending = deque(job for job in state.pending if not uses_retired(job))
            affected = state.assessing is not None and uses_retired(state.assessing)
            if not retired and len(pending) == len(state.pending) and not affected:
                continue

            if retired and decision.action != TurnTakingAction.CANCEL and self._history_turns:
                state.history.append(tuple(record.transcript for record in retired))

            state.pending = pending
            if affected:
                # A model may ignore cancellation; transfer ownership without delaying new speech.
                self._cancel_worker(state)

            if state.current:
                current_ids = {record.observation_id for record in state.current.values()}
                jobs = tuple(state.pending)
                if state.assessing is not None:
                    jobs += (state.assessing,)
                if not any(current_ids.issubset(job.evidence_observation_ids) for job in jobs):
                    self._enqueue(key, state, next(reversed(state.current.values())).observation_id)
                else:
                    self._start_worker(key, state)
            else:
                state.focus_at_turn_start = None
                # Unknown speakers never inherit the previous occupant's conversation focus.
                if key[2] != "entity":
                    self._states.pop(key, None)

    def _consume_turn_annotation(self, event: PerceptionEvent) -> None:
        annotation = event.annotation
        if annotation is None or annotation.kind != AnnotationKind.INTERACTION_TURN:
            return

        decision = TurnTakingDecision.from_annotation(annotation)
        if decision.action in _TERMINAL_ACTIONS:
            self._finish_turn(decision, observation_id=annotation.observation_id)

    def _clear_context(self) -> None:
        for state in self._states.values():
            state.generation += 1
            state.pending.clear()
            self._remember_retired(state.current)
            self._cancel_worker(state)

        self._states.clear()

    """Processor Loop"""

    async def _consume_observations(self) -> None:
        streams = {PerceptionStreamKind.TEXT}

        while True:
            try:
                await self._runtime.perception.wait_for_pending_observations(
                    consumer_id=self.OBSERVATION_CONSUMER_ID, streams=streams
                )
                window = self._runtime.perception.take_pending_observations(
                    consumer_id=self.OBSERVATION_CONSUMER_ID, streams=streams, require_payload=True
                )

                if window.has_gap:
                    logger.warning(
                        "Semantic Addressing observed transcript gap missed=%s", window.missed_count
                    )
                    self._clear_context()

                for observation in window.observations:
                    try:
                        self._consume_transcript(observation)
                    except Exception:
                        logger.exception(
                            "Semantic Addressing failed transcript observation_id=%s",
                            observation.observation_id,
                        )

                self._runtime.perception.commit_observations(window)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Semantic Addressing observation consumer failed")
                await asyncio.sleep(0.05)

    async def _consume_annotations(self) -> None:
        while True:
            try:
                await self._runtime.perception.wait_for_pending_annotations(
                    consumer_id=self.ANNOTATION_CONSUMER_ID
                )
                batch = self._runtime.perception.take_pending_annotations(
                    consumer_id=self.ANNOTATION_CONSUMER_ID,
                    predicate=lambda annotation: annotation.kind == AnnotationKind.INTERACTION_TURN,
                    limit=32,
                )

                if batch.has_gap:
                    logger.warning(
                        "Semantic Addressing observed turn annotation gap missed=%s",
                        batch.missed_count,
                    )
                    self._clear_context()

                for event in batch.items:
                    try:
                        self._consume_turn_annotation(event)
                    except Exception:
                        logger.exception(
                            "Semantic Addressing failed turn annotation event_id=%s", event.event_id
                        )

                self._runtime.perception.commit_annotations(
                    consumer_id=self.ANNOTATION_CONSUMER_ID, cursor_seq=batch.cursor_seq
                )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Semantic Addressing annotation consumer failed")
                await asyncio.sleep(0.05)

    """Runtime operations"""

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        self._tasks = (
            asyncio.create_task(
                self._consume_observations(), name="router_semantic_addressing_observations"
            ),
            asyncio.create_task(
                self._consume_annotations(), name="router_semantic_addressing_annotations"
            ),
        )

        logger.info(
            "Semantic Addressing started model=%s identities=%s history_turns=%s",
            self._model.name,
            self._avatar_identities,
            self._history_turns,
        )

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False
        self._clear_context()

        tasks = (*self._tasks, *self._workers)
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

        self._tasks = ()
        self._workers.clear()
        self._retired_segments.clear()

        self._runtime.perception.clear_observation_consumer(
            self.OBSERVATION_CONSUMER_ID, streams={PerceptionStreamKind.TEXT}
        )
        self._runtime.perception.clear_annotation_consumer(self.ANNOTATION_CONSUMER_ID)

        logger.info("Semantic Addressing stopped")
