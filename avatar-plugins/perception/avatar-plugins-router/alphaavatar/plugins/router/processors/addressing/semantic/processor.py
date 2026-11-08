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
from collections import deque
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.router.enums import (
    AddressingEvidenceKind,
    AddressingMode,
    InteractionEntityKind,
    SemanticAddressingLabel,
)
from alphaavatar.agents.router.schemas import (
    InteractionAddressingEvidence,
    InteractionEntityRef,
    SemanticAddressingRequest,
    SemanticAddressingResult,
    SemanticAddressingTranscript,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSegmentRef
from alphaavatar.core.media import TextPayload
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.time import RuntimeTimeRange
from alphaavatar.core.turn.schemas import TurnSnapshot

from .config import SemanticAddressingConfig
from .factory import create_semantic_addressing_model

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Transcript:
    """A segment's final transcript as perception gave it: what was said, when, through which
    segment, and by whom if its speech named them. Structured here; the model reads the text."""

    segment: PerceptionSegmentRef
    observation_id: str
    time_range: RuntimeTimeRange
    text: str
    entity: PerceptionEntityRef | None = None
    device_id: str | None = None

    @property
    def order(self) -> tuple[int, int, str]:
        return (
            self.time_range.start.monotonic_ns,
            self.time_range.end.monotonic_ns,
            self.observation_id,
        )


@dataclass(frozen=True, slots=True)
class _AssessmentJob:
    target: _Transcript
    context: tuple[str, ...]  # The transcripts its request read, in media order, target last
    request: SemanticAddressingRequest
    speaker: InteractionEntityRef  # The target's own subject, never one of its context's
    queued_ns: int  # When it was queued, on the runtime clock


class SemanticAddressingProcessor(RouterProcessorBase):
    """Judge whom each transcript addresses, in the temporal input since the last committed
    Turn: everyone's speech is one window; each result is its own transcript's alone."""

    OBSERVATION_CONSUMER_ID = "router.addressing.semantic.observations"
    TURN_CONSUMER_ID = "router.addressing.semantic.commits"
    SEMANTIC_SOURCE = "router.addressing.semantic"
    FOCUS_SOURCE = "router.addressing.focus"

    _MAX_WINDOW = 64
    _MAX_RETIRED = 256
    _MAX_PENDING = 2

    def __init__(self, *, runtime: AvatarRuntime, config: SemanticAddressingConfig) -> None:
        super().__init__(runtime=runtime)

        self._model = create_semantic_addressing_model(
            config.model.name, inference_executor=runtime.inference
        )
        self._avatar_identities = config.avatar_identities
        self._history_turns = config.history_turns

        # The window: uncommitted transcripts by segment, since the last committed Turn began.
        self._window: dict[PerceptionSegmentRef, _Transcript] = {}
        self._retired: dict[PerceptionSegmentRef, None] = {}
        self._boundary_ns = 0
        self._context_id: str | None = None

        # Bounded history: committed Turns' words and the focus as the last one committed.
        self._history: deque[tuple[str, ...]] = deque(maxlen=config.history_turns)
        self._focus: tuple[SemanticAddressingLabel, float] | None = None
        self._previous_focus: str | None = None

        self._pending: deque[_AssessmentJob] = deque()
        self._assessing: _AssessmentJob | None = None
        self._worker: asyncio.Task[None] | None = None
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

    """Window operations"""

    def _ordered(self) -> list[_Transcript]:
        return sorted(self._window.values(), key=lambda entry: entry.order)

    def _context(self, target: _Transcript) -> tuple[_Transcript, ...]:
        """What a judgment of the target reads: the window up to it in media time, whoever
        spoke, the target last. Speech after it is not its context."""
        earlier = tuple(e for e in self._ordered() if e is not target and e.order <= target.order)
        return (*earlier, target)

    def _retire(self, segments: Iterable[PerceptionSegmentRef]) -> list[_Transcript]:
        removed = []
        for segment in segments:
            if (entry := self._window.pop(segment, None)) is not None:
                removed.append(entry)
            self._retired[segment] = None
        while len(self._retired) > self._MAX_RETIRED:
            self._retired.pop(next(iter(self._retired)))
        return sorted(removed, key=lambda entry: entry.order)

    """Assessment operations"""

    def _speaker(self, entry: _Transcript) -> InteractionEntityRef:
        # Its own speech's subject, or the association settled for its segment since.
        entity = entry.entity or self._runtime.participants.entity_for_segment(entry.segment)
        return InteractionEntityRef(
            kind=InteractionEntityKind.PERSON,
            entity=entity,
            device_id=entry.device_id,
            source=entry.segment.source,
        )

    def _request(self, context: tuple[_Transcript, ...]) -> SemanticAddressingRequest:
        # The model's text protocol: each earlier Turn one line, then each transcript.
        history = tuple(
            SemanticAddressingTranscript(text=" ".join(turn), final=True) for turn in self._history
        )
        current = tuple(SemanticAddressingTranscript(text=e.text, final=True) for e in context)
        return SemanticAddressingRequest(
            avatar_identities=self._avatar_identities,
            previous_focus=self._previous_focus,
            transcript_segments=(*history, *current),
        )

    def _valid(self, job: _AssessmentJob) -> bool:
        """The window still holds its target and the context it read, unchanged."""
        target = job.target
        return (
            self._window.get(target.segment) is target
            and self._runtime.perception.speech_source_is_current(target.segment.source)
            and tuple(entry.observation_id for entry in self._context(target)) == job.context
        )

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

    def _publish(self, job: _AssessmentJob, result: SemanticAddressingResult) -> None:
        # The target observation alone is annotated; the context is only what it was read with.
        confidence = self._confidence(result.label, result.p_avatar)
        target = job.target.observation_id
        semantic = self._evidence(
            kind=AddressingEvidenceKind.SEMANTIC,
            label=result.label,
            confidence=confidence,
            speaker=job.speaker,
            observation_ids=job.context,
            raw_score=result.p_avatar,
        )
        self._runtime.perception.publish_annotation(
            semantic.to_annotation(source=self.SEMANTIC_SOURCE, observation_id=target)
        )

        if result.label != SemanticAddressingLabel.UNKNOWN:
            self._focus = result.label, confidence
        elif self._focus is not None:
            focus_label, focus_confidence = self._focus
            focus = self._evidence(
                kind=AddressingEvidenceKind.CONVERSATION_FOCUS,
                label=focus_label,
                confidence=focus_confidence,
                speaker=job.speaker,
                observation_ids=job.context,
            )
            self._runtime.perception.publish_annotation(
                focus.to_annotation(source=self.FOCUS_SOURCE, observation_id=target)
            )

        logger.debug(
            "Semantic Addressing label=%s p_avatar=%.4f focus=%s observation_id=%s context=%d",
            result.label.value,
            result.p_avatar,
            self._focus[0].value if self._focus else None,
            target,
            len(job.context),
        )

    @contextmanager
    def _timed(self, job: _AssessmentJob) -> Iterator[None]:
        """The job's inference, from when it was queued: when its turn's addressing evidence
        could be known (O-16). Metadata only, in the input trace."""
        started, outcome = self._runtime.clock.now().monotonic_ns, "done"
        try:
            yield
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "failed"
            raise
        finally:
            segment = job.target.segment
            self._runtime.perception.input_trace.record(
                "addressing.semantic",
                source_id=segment.source.source_id,
                source_generation=segment.source.source_generation,
                segment_id=segment.segment_id,
                observation_id=job.target.observation_id,
                outcome=outcome,
                event_time_ns=job.queued_ns,
                start_time_ns=started,
                end_time_ns=self._runtime.clock.now().monotonic_ns,
            )

    def _cancel_worker(self) -> None:
        # A model may ignore cancellation: transfer ownership without delaying new speech.
        worker, self._worker, self._assessing = self._worker, None, None
        if worker is not None:
            worker.cancel()

    async def _run_jobs(self) -> None:
        worker = asyncio.current_task()
        try:
            while self._worker is worker and self._pending:
                job = self._pending.popleft()
                if not self._valid(job):
                    continue
                self._assessing = job
                try:
                    with self._timed(job):
                        result = await self._model.assess(job.request)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Semantic Addressing inference failed observation_id=%s model=%s",
                        job.target.observation_id,
                        self._model.name,
                    )
                else:
                    # Only a judgment of the window as it still is: never a late, older one.
                    if self._worker is worker and self._valid(job):
                        self._publish(job, result)
                finally:
                    if self._worker is worker and self._assessing is job:
                        self._assessing = None
        finally:
            if self._worker is worker:
                self._worker = self._assessing = None

    def _start_worker(self) -> None:
        if self._pending and (self._worker is None or self._worker.done()):
            self._worker = asyncio.create_task(self._run_jobs(), name="router_semantic_addressing")
            self._workers.add(self._worker)
            self._worker.add_done_callback(self._workers.discard)

    def _enqueue(self, target: _Transcript) -> None:
        context = self._context(target)
        self._pending = deque(job for job in self._pending if job.target.segment != target.segment)
        while len(self._pending) >= self._MAX_PENDING:
            self._pending.popleft()
        self._pending.append(
            _AssessmentJob(
                target=target,
                context=tuple(entry.observation_id for entry in context),
                request=self._request(context),
                speaker=self._speaker(target),
                queued_ns=self._runtime.clock.now().monotonic_ns,
            )
        )
        self._start_worker()

    def _settle(self) -> None:
        """After the window changed: drop the judgments it outdated, and judge its newest
        transcript on it as it is, unless that is already queued or running."""
        self._pending = deque(job for job in self._pending if self._valid(job))
        if self._assessing is not None and not self._valid(self._assessing):
            self._cancel_worker()
        if self._window:
            latest = self._ordered()[-1]
            context = tuple(entry.observation_id for entry in self._context(latest))
            jobs = (*self._pending, *((self._assessing,) if self._assessing else ()))
            if not any(job.target is latest and job.context == context for job in jobs):
                self._enqueue(latest)
        self._start_worker()

    """Input event operations"""

    def _clear(self) -> None:
        self._retire(tuple(self._window))
        self._pending.clear()
        self._cancel_worker()

    def _follow_context(self) -> None:
        """A new conversation context: none of the old one's speech, history or focus."""
        context_id = self._runtime.state.context_id
        if self._context_id is not None and self._context_id != context_id:
            self._clear()
            self._history.clear()
            self._focus = self._previous_focus = None
        self._context_id = context_id

    def _prune(self) -> None:
        # A cancelled or replaced source generation takes its transcripts with it.
        perception = self._runtime.perception
        self._retire(
            tuple(s for s in self._window if not perception.speech_source_is_current(s.source))
        )

    def _consume_transcript(self, observation: EnvObservation) -> None:
        segment = observation.segment
        if observation.kind != ObservationKind.TRANSCRIPT_SEGMENT or segment is None:
            return
        if not self._runtime.participants.observe_source(segment.source):
            return

        self._follow_context()
        self._prune()
        text = self._text(observation)
        if (
            text is None
            or segment in self._retired
            # Speech that ended before the last committed Turn began was superseded by it.
            or observation.time_range.end.monotonic_ns <= self._boundary_ns
            or not self._runtime.perception.speech_source_is_current(segment.source)
        ):
            return

        previous = self._window.get(segment)
        if previous is not None and previous.text == text:
            return  # The same words again: nothing new to judge.

        entry = _Transcript(
            segment=segment,
            observation_id=observation.observation_id,
            time_range=observation.time_range,
            text=text,
            entity=observation.entity,
            device_id=observation.device_id,
        )
        self._window[segment] = entry
        while len(self._window) > self._MAX_WINDOW:
            self._retire((self._ordered()[0].segment,))
        # Judged at once, identity or no; a transcript out of order changes the newest's context.
        self._enqueue(entry)
        self._settle()

    def _acknowledge(self, snapshot: TurnSnapshot) -> None:
        """A committed Turn: the input it owns leaves the window and becomes history; speech
        that ended before it began was superseded. A proposed decision never does this."""
        self._follow_context()
        owned = set(snapshot.input_observation_ids)
        covered = {
            observation.segment
            for event in snapshot.perception_events
            if (observation := event.observation) is not None
            and observation.observation_id in owned
            and observation.segment is not None
        }
        committed = self._retire(covered)
        if committed and self._history_turns:
            self._history.append(tuple(entry.text for entry in committed))

        self._boundary_ns = max(self._boundary_ns, snapshot.started_at.monotonic_ns)
        self._retire(
            tuple(
                entry.segment
                for entry in self._window.values()
                if entry.time_range.end.monotonic_ns <= self._boundary_ns
            )
        )
        self._previous_focus = self._focus[0].value if self._focus else None
        self._settle()

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
                    self._clear()

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

    async def _consume_turns(self) -> None:
        stream = self._runtime.turn.events
        while await stream.wait_for_pending(consumer_id=self.TURN_CONSUMER_ID):
            batch = stream.read_pending(consumer_id=self.TURN_CONSUMER_ID)
            if batch.has_gap:
                # Which input those Turns owned is unknown: none of the window can be trusted.
                logger.warning("Semantic Addressing missed committed Turns")
                self._clear()
            for event in batch.items:
                try:
                    self._acknowledge(event.snapshot)
                except Exception:
                    logger.exception(
                        "Semantic Addressing failed turn_id=%s", event.snapshot.turn_id
                    )
            stream.commit(consumer_id=self.TURN_CONSUMER_ID, cursor_seq=batch.cursor_seq)

    """Runtime operations"""

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        self._context_id = self._runtime.state.context_id
        self._tasks = (
            asyncio.create_task(
                self._consume_observations(), name="router_semantic_addressing_observations"
            ),
            asyncio.create_task(self._consume_turns(), name="router_semantic_addressing_commits"),
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
        self._clear()

        tasks = (*self._tasks, *self._workers)
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

        self._tasks = ()
        self._workers.clear()
        self._retired.clear()
        self._history.clear()
        self._focus = self._previous_focus = None

        self._runtime.perception.clear_observation_consumer(
            self.OBSERVATION_CONSUMER_ID, streams={PerceptionStreamKind.TEXT}
        )
        self._runtime.turn.events.clear_consumer(self.TURN_CONSUMER_ID)

        logger.info("Semantic Addressing stopped")
