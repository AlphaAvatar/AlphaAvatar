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
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from alphaavatar.agents.router import (
    AddressingEvidenceKind,
    AddressingMode,
    InteractionAddressingEvidence,
    InteractionEntityKind,
    InteractionEntityRef,
    RouterProcessorBase,
    SemanticAddressingLabel,
    SemanticAddressingModelBase,
    SemanticAddressingRequest,
    SemanticAddressingResult,
    SemanticAddressingTranscript,
    TurnTakingAction,
    TurnTakingDecision,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import (
    AnnotationKind,
    EnvObservation,
    ObservationKind,
    PerceptionSegmentRef,
)
from alphaavatar.core.media import TextPayload
from alphaavatar.core.perception import PerceptionEvent, PerceptionStreamKind

from ...log import logger

SpeakerKey = tuple[str, str]

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
    worker: asyncio.Task[None] | None = None


class SemanticAddressingProcessor(RouterProcessorBase):
    OBSERVATION_CONSUMER_ID = "router.addressing.semantic.observations"
    ANNOTATION_CONSUMER_ID = "router.addressing.semantic.annotations"
    SEMANTIC_SOURCE = "router.addressing.semantic"
    FOCUS_SOURCE = "router.addressing.focus"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        model: SemanticAddressingModelBase,
        avatar_identities: tuple[str, ...],
        history_turns: int = 2,
    ) -> None:
        super().__init__(runtime=runtime)
        identities = tuple(
            dict.fromkeys(identity.strip() for identity in avatar_identities if identity.strip())
        )
        if not identities:
            raise ValueError("avatar_identities cannot be empty")
        if history_turns < 0:
            raise ValueError("history_turns cannot be negative")

        self._model = model
        self._avatar_identities = identities
        self._history_turns = history_turns
        self._states: dict[SpeakerKey, _SpeakerState] = {}
        self._workers: set[asyncio.Task[None]] = set()
        self._tasks: tuple[asyncio.Task[None], ...] = ()
        self._started = False

    @property
    def name(self) -> str:
        return "semantic_addressing"

    @staticmethod
    def _key_from_observation(observation: EnvObservation) -> SpeakerKey:
        if observation.transport_participant_id:
            return "participant", observation.transport_participant_id
        if observation.entity is not None:
            return "entity", observation.entity.perception_entity_id
        return "anonymous", "session"

    @staticmethod
    def _key_from_entity(entity: InteractionEntityRef) -> SpeakerKey:
        if entity.transport_participant_id:
            return "participant", entity.transport_participant_id
        if entity.entity is not None:
            return "entity", entity.entity.perception_entity_id
        return "anonymous", "session"

    @staticmethod
    def _speaker(observation: EnvObservation) -> InteractionEntityRef:
        return InteractionEntityRef(
            kind=InteractionEntityKind.PERSON,
            entity=observation.entity,
            transport_participant_id=observation.transport_participant_id,
        )

    @staticmethod
    def _text(observation: EnvObservation) -> str | None:
        payload = observation.payload
        if not isinstance(payload, TextPayload):
            return None
        return payload.text.strip() or None

    def _state(self, observation: EnvObservation) -> tuple[SpeakerKey, _SpeakerState]:
        key = self._key_from_observation(observation)
        speaker = self._speaker(observation)
        state = self._states.get(key)

        if state is None:
            state = _SpeakerState(speaker=speaker, history=deque(maxlen=self._history_turns))
            self._states[key] = state
        else:
            state.speaker = speaker

        return key, state

    @staticmethod
    def _history_segments(state: _SpeakerState) -> tuple[SemanticAddressingTranscript, ...]:
        return tuple(
            SemanticAddressingTranscript(
                text=" ".join(segment.text for segment in turn).strip(),
                final=True,
            )
            for turn in state.history
            if any(segment.text.strip() for segment in turn)
        )

    def _request(self, state: _SpeakerState) -> SemanticAddressingRequest:
        current = tuple(record.transcript for record in state.current.values())
        return SemanticAddressingRequest(
            avatar_identities=self._avatar_identities,
            previous_focus=state.focus_at_turn_start,
            transcript_segments=(*self._history_segments(state), *current),
        )

    def _enqueue(self, key: SpeakerKey, state: _SpeakerState, observation: EnvObservation) -> None:
        state.pending.append(
            _AssessmentJob(
                generation=state.generation,
                request=self._request(state),
                speaker=state.speaker,
                observation_id=observation.observation_id,
                evidence_observation_ids=tuple(
                    record.observation_id for record in state.current.values()
                ),
            )
        )

        if state.worker is None or state.worker.done():
            state.worker = asyncio.create_task(
                self._run_jobs(key, state),
                name=f"router_semantic_addressing:{key[0]}:{key[1]}",
            )
            self._workers.add(state.worker)
            state.worker.add_done_callback(self._workers.discard)

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
        self,
        state: _SpeakerState,
        job: _AssessmentJob,
        result: SemanticAddressingResult,
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
            semantic.to_annotation(
                source=self.SEMANTIC_SOURCE,
                observation_id=job.observation_id,
            )
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
                focus.to_annotation(
                    source=self.FOCUS_SOURCE,
                    observation_id=job.observation_id,
                )
            )

        logger.debug(
            "Semantic Addressing label=%s p_avatar=%.4f focus=%s observation_id=%s",
            result.label.value,
            result.p_avatar,
            state.focus[0].value if state.focus else None,
            job.observation_id,
        )

    async def _run_jobs(self, key: SpeakerKey, state: _SpeakerState) -> None:
        try:
            while state.pending:
                job = state.pending.popleft()

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
                    continue

                if self._states.get(key) is state and state.generation == job.generation:
                    self._publish(state, job, result)

        finally:
            if state.worker is asyncio.current_task():
                state.worker = None

    def _consume_transcript(self, observation: EnvObservation) -> None:
        if observation.kind != ObservationKind.TRANSCRIPT_SEGMENT or observation.segment is None:
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
        self._enqueue(key, state, observation)

    def _finish_turn(self, decision: TurnTakingDecision) -> None:
        if decision.actor is None:
            return

        state = self._states.get(self._key_from_entity(decision.actor))
        if state is None:
            return

        if state.current and decision.action != TurnTakingAction.CANCEL and self._history_turns:
            state.history.append(tuple(record.transcript for record in state.current.values()))

        state.generation += 1
        state.current.clear()
        state.pending.clear()
        state.focus_at_turn_start = None

    def _consume_turn_annotation(self, event: PerceptionEvent) -> None:
        annotation = event.annotation
        if annotation is None or annotation.kind != AnnotationKind.INTERACTION_TURN:
            return

        decision = TurnTakingDecision.from_annotation(annotation)
        if decision.action in _TERMINAL_ACTIONS:
            self._finish_turn(decision)

    def _clear_context(self) -> None:
        for state in self._states.values():
            state.generation += 1
            state.pending.clear()

        self._states.clear()

    async def _consume_observations(self) -> None:
        streams = {PerceptionStreamKind.TEXT}

        while True:
            try:
                await self._runtime.perception.wait_for_pending_observations(
                    consumer_id=self.OBSERVATION_CONSUMER_ID,
                    streams=streams,
                )
                window = self._runtime.perception.take_pending_observations(
                    consumer_id=self.OBSERVATION_CONSUMER_ID,
                    streams=streams,
                    require_payload=True,
                )

                if window.has_gap:
                    logger.warning(
                        "Semantic Addressing observed transcript gap missed=%s",
                        window.missed_count,
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
                    consumer_id=self.ANNOTATION_CONSUMER_ID,
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
                            "Semantic Addressing failed turn annotation event_id=%s",
                            event.event_id,
                        )

                self._runtime.perception.commit_annotations(
                    consumer_id=self.ANNOTATION_CONSUMER_ID,
                    cursor_seq=batch.cursor_seq,
                )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Semantic Addressing annotation consumer failed")
                await asyncio.sleep(0.05)

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        self._tasks = (
            asyncio.create_task(
                self._consume_observations(),
                name="router_semantic_addressing_observations",
            ),
            asyncio.create_task(
                self._consume_annotations(),
                name="router_semantic_addressing_annotations",
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

        for task in self._tasks:
            task.cancel()
        for task in tuple(self._workers):
            task.cancel()

        await asyncio.gather(*self._tasks, *self._workers, return_exceptions=True)

        self._tasks = ()
        self._workers.clear()
        self._states.clear()

        self._runtime.perception.clear_observation_consumer(
            self.OBSERVATION_CONSUMER_ID,
            streams={PerceptionStreamKind.TEXT},
        )
        self._runtime.perception.clear_annotation_consumer(self.ANNOTATION_CONSUMER_ID)

        logger.info("Semantic Addressing stopped")
