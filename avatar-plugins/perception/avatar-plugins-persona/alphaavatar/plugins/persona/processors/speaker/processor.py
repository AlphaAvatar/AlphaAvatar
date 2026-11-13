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
import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from alphaavatar.agents.constants import SPEAKER_MATCH_THRESHOLD
from alphaavatar.agents.persona import PersonaProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import avatar_capability
from alphaavatar.agents.runtime.capability.enums import AvatarCapabilityName
from alphaavatar.agents.utils.vector import VectorOps
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import AudioFrame, AudioSegmentPayload, PayloadFormatUnavailable
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session.enums import IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import IdentityRequest, Participant
from alphaavatar.core.turn.schemas import TurnSnapshot

from ...runtime import PersonaRuntime
from .attribute_runner import SpeakerAttributeRunner
from .cache import SpeakerCache
from .config import SpeakerConfig
from .model_files import SPEAKER_MODEL_CONFIG
from .tracking import SpeakerTracks
from .vector_runner import SpeakerVectorRunner

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ShortSpeech:
    """A source's short speech not inferred yet: its consecutive short segments' audio in order,
    their VAD seconds, and each one's association, for the segment that comes next to carry."""

    pcm: bytes = b""
    seconds: float = 0.0
    segments: tuple[tuple[PerceptionSegmentRef, int], ...] = ()


@dataclass(slots=True)
class SpeakerSegmentState:
    segment: PerceptionSegmentRef
    entity: PerceptionEntityRef | None
    participant: Participant | None  # Its association's; once identified, its attributes' too
    token: int
    device_id: str | None = None
    pcm: bytearray = field(default_factory=bytearray)
    recent: bytearray = field(default_factory=bytearray)
    seen: dict[str, None] = field(default_factory=dict)  # Its frames' observations, oldest first
    window_index: int = 0
    pending: int = 0
    closed: bool = False
    invalid: bool = False
    inference_failed: bool = False
    vector: np.ndarray | None = None
    vector_sec: float = 0.0  # Seconds of audio its vector is from: a window's, or its own
    last_audio: bytes | None = None
    identified: asyncio.Event = field(default_factory=asyncio.Event)  # Matched, or never will be
    # The short speech of its source just before it, which leads its own audio; the segments it
    # is from take the association its vector finds.
    led: _ShortSpeech = field(default_factory=_ShortSpeech)


@dataclass(slots=True, frozen=True)
class SpeakerWindow:
    state: SpeakerSegmentState
    audio_f32: bytes
    index: int = 0
    queued_ns: int = 0  # When it joined the inference queue, on the runtime clock
    whole: bool = False  # A segment shorter than a window, at its own length

    @property
    def source(self) -> PerceptionSourceRef:
        return self.state.segment.source


@avatar_capability(
    name=AvatarCapabilityName.PERSONA_SPEAKER_RECOGNITION,
    description="Can recognize known users from individually associated speech and infer speaker attributes.",
)
class SpeakerProcessor(PersonaProcessorBase):
    CONSUMER_ID = "persona.speaker"
    MAX_SEEN_OBSERVATIONS = 2048
    MAX_RETIRED_SEGMENTS = 512
    ATTRIBUTE_INTERVAL_SEC = 5.0

    def __init__(
        self, *, runtime: AvatarRuntime, persona: PersonaRuntime, config: SpeakerConfig
    ) -> None:
        super().__init__(runtime=runtime, persona=persona)

        self._config = config
        self._vector_config = SPEAKER_MODEL_CONFIG[SpeakerVectorRunner.MODEL_TYPE]
        self._attribute_config = SPEAKER_MODEL_CONFIG[SpeakerAttributeRunner.MODEL_TYPE]
        if self._vector_config.sample_rate != self._attribute_config.sample_rate:
            raise ValueError("Speaker vector and attribute models must use the same sample rate")

        self._sample_rate = self._vector_config.sample_rate
        self._window_bytes = self._vector_config.window_size_samples * 2
        self._step_bytes = self._vector_config.step_size_samples * 2

        self._segments: dict[PerceptionSegmentRef, SpeakerSegmentState] = {}
        self._retired_segments: dict[PerceptionSegmentRef, None] = {}
        self._profile_caches: dict[str, SpeakerCache] = {}
        self._attribute_times: dict[str, float] = {}
        self._shorts: dict[PerceptionSourceRef, _ShortSpeech] = {}
        self._tracks = SpeakerTracks(
            threshold=config.track_match_threshold, margin=config.track_match_margin
        )

        # Three lanes: windows and the association Engine resolves a Turn's actors from; each
        # bound segment's identity, which its Turn's Context waits for within its bound; and
        # its speaker's attributes, which nothing waits for.
        self._inference_queue: asyncio.Queue[SpeakerWindow | SpeakerSegmentState] = asyncio.Queue(
            maxsize=config.inference_queue_size
        )
        self._identity_queue: asyncio.Queue[SpeakerSegmentState] = asyncio.Queue(
            maxsize=config.inference_queue_size
        )
        self._attribute_queue: asyncio.Queue[SpeakerSegmentState] = asyncio.Queue(
            maxsize=config.inference_queue_size
        )

        self._consume_task: asyncio.Task[None] | None = None
        self._lanes: tuple[asyncio.Task[None], ...] = ()
        self._running: dict[str, tuple[SpeakerSegmentState, asyncio.Task[None]]] = {}

    @property
    def name(self) -> str:
        return "speaker"

    def _extract_frame(self, observation: EnvObservation) -> AudioFrame | None:
        if observation.payload is None:
            return None
        try:
            frame = observation.payload.get(
                PayloadFormat.AUDIO_FRAME, view=PayloadView.RAW, fallback_to_raw=False
            )
        except PayloadFormatUnavailable:
            return None
        return frame if isinstance(frame, AudioFrame) else None

    def _segment_pcm(self, observation: EnvObservation) -> bytes | None:
        """A segment's canonical audio, the payload its transcription reads, when it is shorter
        than a window."""
        payload = observation.payload
        if (
            not isinstance(payload, AudioSegmentPayload)
            or payload.sample_rate != self._sample_rate
            or payload.num_channels != 1
        ):
            return None
        try:
            pcm = payload.get(
                PayloadFormat.AUDIO_PCM16_BYTES, view=PayloadView.RAW, fallback_to_raw=False
            )
        except PayloadFormatUnavailable:
            return None
        return pcm if isinstance(pcm, bytes) and 0 < len(pcm) < self._window_bytes else None

    def _is_current(self, state: SpeakerSegmentState) -> bool:
        return self._segments.get(
            state.segment
        ) is state and self.runtime.participants.segment_is_current(state.segment, state.token)

    def _retire(self, state: SpeakerSegmentState) -> None:
        self.runtime.participants.finish_segment_resolution(state.segment, token=state.token)
        if self._segments.get(state.segment) is state:
            self._segments.pop(state.segment)

        state.pcm.clear()
        state.recent.clear()
        state.last_audio = None
        state.seen.clear()
        state.identified.set()
        self._retired_segments[state.segment] = None
        if len(self._retired_segments) > self.MAX_RETIRED_SEGMENTS:
            self._retired_segments.pop(next(iter(self._retired_segments)))

    def _invalidate(self, state: SpeakerSegmentState) -> None:
        state.invalid = True
        self.runtime.participants.bind_segment(state.segment, None, token=state.token)

    def _release_tracks(self) -> None:
        for entity in self._tracks.drain_retired():
            self.runtime.participants.release_entity(entity)

    def _discard_job(self, job: SpeakerWindow | SpeakerSegmentState) -> None:
        state = job.state if isinstance(job, SpeakerWindow) else job
        if isinstance(job, SpeakerWindow):
            state.pending -= 1
        if self._segments.get(state.segment) is state:
            state.inference_failed = True
            self.runtime.participants.finish_segment_resolution(state.segment, token=state.token)
            if state.closed and state.pending == 0:
                self._retire(state)

    def _enqueue(self, job: SpeakerWindow | SpeakerSegmentState) -> None:
        if self._inference_queue.full():
            self._discard_job(self._inference_queue.get_nowait())
        self._inference_queue.put_nowait(job)

    def _enqueue_identity(self, state: SpeakerSegmentState) -> None:
        if self._identity_queue.full():
            self._retire(self._identity_queue.get_nowait())  # Bound, never identified
        self._identity_queue.put_nowait(state)

    def _enqueue_attribute(self, state: SpeakerSegmentState) -> None:
        if self._attribute_queue.full():
            self._retire(self._attribute_queue.get_nowait())  # Identified, never described
        self._attribute_queue.put_nowait(state)

    def _enqueue_pcm(
        self, state: SpeakerSegmentState, pcm16: bytes, *, whole: bool = False
    ) -> None:
        audio = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        state.window_index += 1
        state.pending += 1
        queued = self.runtime.clock.now().monotonic_ns
        self._enqueue(SpeakerWindow(state, audio.tobytes(), state.window_index, queued, whole))

    def _state(self, observation: EnvObservation) -> SpeakerSegmentState | None:
        segment = observation.segment
        if segment is None or segment in self._retired_segments:
            return None

        if not self.runtime.participants.observe_source(segment.source):
            return None

        for current in tuple(self._segments.values()):
            if (
                current.segment.source.source_id == segment.source.source_id
                and current.segment.source.source_generation < segment.source.source_generation
            ):
                self._invalidate(current)
                self._retire(current)

        for source in tuple(self._shorts):
            if (
                source.source_id == segment.source.source_id
                and source.source_generation < segment.source.source_generation
            ):
                del self._shorts[source]

        state = self._segments.get(segment)
        if state is not None:
            if state.device_id is None:
                state.device_id = observation.device_id
            elif observation.device_id is not None and state.device_id != observation.device_id:
                self._invalidate(state)
                self._retire(state)
                return None

        if state is not None and not self.runtime.participants.segment_is_current(
            segment, state.token
        ):
            self._retire(state)
            return None

        if state is None:
            if len(self._segments) >= self._config.max_segments:
                removed = next(iter(self._segments.values()))
                self._invalidate(removed)
                self._retire(removed)

            token = self.runtime.participants.observe_segment(segment)
            entity = observation.entity
            try:
                participant = (
                    self.runtime.participants.ensure_entity(
                        segment.source, entity, kind="speaker", device_id=observation.device_id
                    )
                    if entity is not None
                    else None
                )
            except Exception:
                self.runtime.participants.finish_segment_resolution(segment, token=token)
                raise

            state = SpeakerSegmentState(
                segment=segment,
                entity=entity,
                participant=participant,
                token=token,
                device_id=observation.device_id,
            )
            self._segments[segment] = state
            # Its source's short speech leads it; a segment with its own subject drops it.
            if (led := self._shorts.pop(segment.source, None)) is not None and entity is None:
                state.led = led
                state.pcm.extend(led.pcm)
                state.recent.extend(led.pcm[-self._window_bytes :])
        elif observation.entity is not None and observation.entity != state.entity:
            if state.entity is not None:
                # Conflicting explicit subjects invalidate the physical association.
                self._invalidate(state)
            else:
                entity = observation.entity
                try:
                    associated = self.runtime.participants.ensure_entity(
                        segment.source, entity, kind="speaker", device_id=state.device_id
                    )
                except Exception:
                    self._retire(state)
                    raise
                state.entity = entity
                state.participant = associated

        # An explicit subject is usable before optional identity inference has completed.
        if state.entity is not None and not state.invalid:
            self.runtime.participants.ensure_entity(
                segment.source, state.entity, kind="speaker", device_id=state.device_id
            )
            if not self.runtime.participants.bind_segment(segment, state.entity, token=state.token):
                state.invalid = True

        return state

    def _append_frame(self, observation: EnvObservation, frame: AudioFrame) -> None:
        if frame.sample_rate != self._sample_rate or frame.num_channels != 1:
            return

        state = self._state(observation)
        if state is None or state.closed or state.invalid or state.inference_failed:
            return

        observation_id = str(
            observation.metadata.get("source_observation_id") or observation.observation_id
        )
        if observation_id in state.seen:
            return

        state.seen[observation_id] = None
        if len(state.seen) > self.MAX_SEEN_OBSERVATIONS:
            state.seen.pop(next(iter(state.seen)))

        state.pcm.extend(frame.data)
        state.recent.extend(frame.data)
        del state.recent[: -self._window_bytes]
        while len(state.pcm) >= self._window_bytes:
            self._enqueue_pcm(state, bytes(state.pcm[: self._window_bytes]))
            del state.pcm[: self._step_bytes]

    def _close_segment(self, observation: EnvObservation) -> None:
        state = self._state(observation)
        if state is None or state.closed:
            return

        # Include the final tail in a full window: after a window, its buffer keeps that window
        # less a step, and anything beyond is tail. Speech that never filled one is inferred
        # once at its own length, after the short speech that leads it. Neither is padded.
        if not state.invalid and not state.inference_failed:
            if (
                len(state.recent) == self._window_bytes
                and len(state.pcm) > self._window_bytes - self._step_bytes
            ):
                self._enqueue_pcm(state, bytes(state.recent))
            elif state.window_index == 0 and (pcm := self._segment_pcm(observation)) is not None:
                seconds = observation.time_range.duration_sec
                if state.entity is None and seconds < self._config.short_segment_sec:
                    self._add_short(state, state.led.pcm + pcm, state.led.seconds + seconds)
                else:
                    self._enqueue_pcm(state, state.led.pcm + pcm, whole=True)

        state.closed = True
        state.pcm.clear()
        state.recent.clear()
        if state.pending == 0:
            if state.invalid or state.inference_failed or state.vector is None:
                # No vector job to wait for; finish without joining the queue.
                self._retire(state)
            else:
                self._enqueue(state)

    def _add_short(self, state: SpeakerSegmentState, pcm: bytes, seconds: float) -> None:
        """A short segment is not matched alone, and its Turn never waits on it. With the short
        speech it carries, it is inferred once together they reach short_merge_sec, each of them
        taking the association its vector finds; until then, it is carried on to lead the next
        segment of its source. A short speech is never above that bound here, so a segment with
        its own subject, which cannot carry it, drops it."""
        state.identified.set()
        if seconds >= self._config.short_merge_sec:
            self._enqueue_pcm(state, pcm, whole=True)
            return
        self._shorts[state.segment.source] = _ShortSpeech(
            pcm, seconds, (*state.led.segments, (state.segment, state.token))
        )

    def _cancel_source(self, source: PerceptionSourceRef) -> None:
        self._shorts.pop(source, None)
        for state in tuple(self._segments.values()):
            if state.segment.source == source:
                self._invalidate(state)
                self._retire(state)

        # Its segments go with it; its voices stay the session's, for its other sources too.
        self.runtime.participants.retire_source(source)
        for state, job in self._running.values():
            if state.segment.source == source:
                job.cancel()

    @contextlib.asynccontextmanager
    async def _timed(
        self, stage: str, state: SpeakerSegmentState, **fields: int | None
    ) -> AsyncIterator[None]:
        """A step's span on its lane, in the trace: done, timed out, cancelled or failed;
        bounded, metadata only, never waited on."""
        started, outcome = self.runtime.clock.now().monotonic_ns, "failed"
        try:
            yield
            outcome = "done"
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                outcome = "cancelled"
            elif isinstance(error, TimeoutError):
                outcome = "timeout"
            raise
        finally:
            segment = state.segment
            self.perception_runtime.input_trace.record(
                stage,
                source_id=segment.source.source_id,
                source_generation=segment.source.source_generation,
                segment_id=segment.segment_id,
                outcome=outcome,
                start_time_ns=started,
                end_time_ns=self.runtime.clock.now().monotonic_ns,
                **fields,
            )

    async def _infer_window(self, job: SpeakerWindow) -> None:
        state = job.state
        if not self._is_current(state) or state.invalid or state.inference_failed:
            return

        # Each window's wait in the queue and its inference, for the association (O-16).
        timed = self._timed(
            "speaker.window", state, sequence=job.index, event_time_ns=job.queued_ns or None
        )
        async with timed:
            result = await asyncio.wait_for(
                self.inference_executor.do_inference(
                    SpeakerVectorRunner.INFERENCE_METHOD, job.audio_f32
                ),
                timeout=self._vector_config.inference_timeout_sec,
            )
        if not self._is_current(state) or state.invalid or state.inference_failed:
            return

        if result is None:
            raise RuntimeError("Speaker vector runner returned no result")

        vector = VectorOps.norm(np.frombuffer(result, dtype=np.float32))
        if vector is None:
            raise ValueError("Speaker vector must contain finite values and have a positive norm")

        if state.vector is not None:
            if state.vector.shape != vector.shape:
                raise ValueError("Speaker vector shape changed within a segment")
            if float(np.dot(state.vector, vector)) < self._config.segment_consistency_threshold:
                self._invalidate(state)
                return

        if state.vector is None:
            state.vector = vector.copy()
            state.vector_sec = len(job.audio_f32) // 4 / self._sample_rate

        # Attributes keep their own input: full windows only.
        if not job.whole:
            state.last_audio = job.audio_f32

    async def _resolve_identity(
        self, state: SpeakerSegmentState, participant: Participant
    ) -> Participant | None:
        if not self.runtime.participants.accepts_identity(participant):
            return None

        user_id = await self.persona.store.search_speaker_vector(
            speaker_vector=state.vector,
            threshold=SPEAKER_MATCH_THRESHOLD,
            timeout=self._vector_config.inference_timeout_sec,
        )
        if (
            not self._is_current(state)
            or state.invalid
            or not self.runtime.participants.accepts_identity(participant)
        ):
            return None

        current = self.runtime.participants.resolve(
            source=state.segment.source, entity=state.entity, segment=state.segment
        )
        if current is None or current.participant_id != participant.participant_id:
            return None

        if user_id is not None:
            outcome = self.runtime.participants.bind_user(
                IdentityRequest(
                    participant_id=participant.participant_id,
                    user_id=user_id,
                    source=IdentitySource.PERCEPTION,
                    expected_revision=participant.identity_revision,
                    reason=f"Speaker vector matched the stored user above {SPEAKER_MATCH_THRESHOLD}",
                )
            )
            if outcome not in (IdentityOutcome.APPLIED, IdentityOutcome.UNCHANGED):
                return None

        cache = self.persona.cache_for(participant.participant_id)
        if cache is None:
            return None

        cache.add_speaker_vector(state.vector, state.vector_sec)
        return cache.participant

    def _attribute_due(self, state: SpeakerSegmentState, participant: Participant) -> bool:
        last = self._attribute_times.get(participant.participant_id, -float("inf"))
        return (
            state.last_audio is not None and time.monotonic() - last >= self.ATTRIBUTE_INTERVAL_SEC
        )

    async def _infer_attribute(self, state: SpeakerSegmentState, participant: Participant) -> None:
        if not self._attribute_due(state, participant):
            return

        now = time.monotonic()

        result = await asyncio.wait_for(
            self.inference_executor.do_inference(
                SpeakerAttributeRunner.INFERENCE_METHOD, state.last_audio
            ),
            timeout=self._attribute_config.inference_timeout_sec,
        )
        if not self._is_current(state) or not self.runtime.participants.accepts_identity(
            participant
        ):
            return

        current = self.runtime.participants.resolve(
            source=state.segment.source, entity=state.entity, segment=state.segment
        )
        if current is None or current.participant_id != participant.participant_id:
            return

        if result is None:
            raise RuntimeError("Speaker attribute runner returned no result")

        cache = self.persona.cache_for(participant.participant_id)
        if cache is None:
            return

        if (
            participant.participant_id not in self._profile_caches
            and len(self._profile_caches) >= self._config.max_speaker_caches
        ):
            removed = next(iter(self._profile_caches))
            self._profile_caches.pop(removed)
            self._attribute_times.pop(removed, None)

        profile = self._profile_caches.setdefault(participant.participant_id, SpeakerCache())
        cache.profile_details = profile.update_profile_detail(
            cache.profile_details,
            SpeakerAttributeRunner.decode(result),
            updated_at=datetime.fromtimestamp(self.runtime.clock.now().unix_seconds, UTC),
        )
        self._attribute_times[participant.participant_id] = now

    """Processor Loop"""

    async def _finish_segment(self, state: SpeakerSegmentState) -> None:
        if not self._is_current(state) or not state.closed or state.pending:
            return

        identifying = False
        try:
            if state.invalid:
                return

            if state.entity is None:
                if state.vector is None or state.inference_failed:
                    return

                state.entity = self._tracks.resolve(
                    state.segment.source, state.vector, state.vector_sec
                )
                if state.entity is None:
                    return

                associated = self.runtime.participants.ensure_entity(
                    state.segment.source, state.entity, kind="speaker", device_id=state.device_id
                )
                # Its identity step judges against this version: a change while it searches stays.
                state.participant = associated

            if not self.runtime.participants.bind_segment(
                state.segment, state.entity, token=state.token
            ):
                return
            for segment, token in state.led.segments:
                self.runtime.participants.bind_segment(segment, state.entity, token=token)

            if self.runtime.participants.resolve(segment=state.segment) is None:
                return

            if state.participant is None or state.vector is None or state.inference_failed:
                return

            # Off this lane: the next segment's windows and association never wait on it.
            self._enqueue_identity(state)
            identifying = True
        finally:
            if not identifying:
                self._retire(state)

    async def _identify(self, state: SpeakerSegmentState) -> None:
        """A bound segment's identity, which the Turn its speech is in waits for within its
        bound; its speaker's attributes, when due, go to their own lane."""
        describing = False
        try:
            if not self._is_current(state) or state.participant is None:
                return

            async with self._timed("speaker.identity", state):
                participant = await self._resolve_identity(state, state.participant)

            if participant is not None and self._attribute_due(state, participant):
                state.participant = participant
                self._enqueue_attribute(state)
                describing = True
        finally:
            state.identified.set()
            if not describing:
                self._retire(state)

    async def _describe(self, state: SpeakerSegmentState) -> None:
        """An identified segment's speaker attributes: they reach later Turns, never a Turn's
        wait, and only the identity they were inferred for."""
        try:
            if self._is_current(state) and state.participant is not None:
                async with self._timed("speaker.attribute", state):
                    await self._infer_attribute(state, state.participant)
        finally:
            self._retire(state)

    async def _process(self, job: SpeakerWindow | SpeakerSegmentState) -> None:
        state = job.state if isinstance(job, SpeakerWindow) else job
        try:
            if isinstance(job, SpeakerWindow):
                await self._infer_window(job)

        except BaseException:
            if self._is_current(state):
                # Missing model evidence must not revoke an explicit physical association.
                state.inference_failed = True
                self.runtime.participants.finish_segment_resolution(
                    state.segment, token=state.token
                )
            raise

        finally:
            if isinstance(job, SpeakerWindow):
                state.pending -= 1

            if not self._is_current(state) or (
                state.closed and state.pending == 0 and (state.invalid or state.inference_failed)
            ):
                self._retire(state)

        await self._finish_segment(state)

    async def _serve(
        self, lane: str, queue: asyncio.Queue, process: Callable[..., Awaitable[None]]
    ) -> None:
        """One lane's jobs, one at a time: a cancelled source cancels the one it runs."""
        while True:
            job = await queue.get()
            state = job.state if isinstance(job, SpeakerWindow) else job
            running = asyncio.create_task(process(job), name=f"persona_speaker_{lane}")
            self._running[lane] = (state, running)

            try:
                await running
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                logger.exception(
                    "Speaker %s failed source=%s segment=%s",
                    lane,
                    state.segment.source,
                    state.segment.segment_id,
                )
            finally:
                self._running.pop(lane, None)

    async def _consume_loop(self) -> None:
        stream = self.perception_runtime.speech
        while True:
            try:
                await stream.wait_for_pending(consumer_id=self.CONSUMER_ID)
                batch = stream.read_pending(consumer_id=self.CONSUMER_ID)
                if batch.has_gap:
                    for state in tuple(self._segments.values()):
                        self._invalidate(state)
                        self._retire(state)
                    self._shorts.clear()  # Their order is lost with what was missed

                for observation in batch.items:
                    if observation.kind == ObservationKind.SPEECH_CANCELLED:
                        self._cancel_source(observation.source)
                    elif observation.kind == ObservationKind.SPEECH_SEGMENT:
                        self._close_segment(observation)
                    elif observation.kind == ObservationKind.SPEECH_FRAME:
                        frame = self._extract_frame(observation)
                        if frame is not None:
                            self._append_frame(observation, frame)
                stream.commit(consumer_id=self.CONSUMER_ID, cursor_seq=batch.cursor_seq)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Persona Speaker failed to consume speech observations")
                await asyncio.sleep(0.05)

    async def _await_identities(self, snapshot: TurnSnapshot) -> None:
        """What a Turn's answer needs of its speech before Context freezes: each segment's
        speaker identity, settled within the bound or left as it is. Attributes go on unwaited,
        reaching later Turns only."""
        owned = set(snapshot.input_observation_ids)
        segments = {
            observation.segment
            for event in snapshot.perception_events
            if (observation := event.observation) is not None
            and observation.observation_id in owned
            and observation.segment is not None
        }
        pending = [
            state.identified.wait()
            for state in self._segments.values()
            if state.segment in segments
        ]
        if pending:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(self._config.identity_wait_sec):
                    await asyncio.gather(*pending)

    """Runtime operations"""

    async def _start(self) -> None:
        self.runtime.turn.register_context_consumer(self.CONSUMER_ID, waiter=self._await_identities)
        self._lanes = (
            asyncio.create_task(
                self._serve("window", self._inference_queue, self._process),
                name="persona_speaker_inference",
            ),
            asyncio.create_task(
                self._serve("identity", self._identity_queue, self._identify),
                name="persona_speaker_identity",
            ),
            asyncio.create_task(
                self._serve("attribute", self._attribute_queue, self._describe),
                name="persona_speaker_attribute",
            ),
        )
        self._consume_task = asyncio.create_task(
            self._consume_loop(), name="persona_speaker_consumer"
        )
        logger.info(
            "Persona Speaker started sample_rate=%s queue_size=%s",
            self._sample_rate,
            self._inference_queue.maxsize,
        )

    async def _stop(self, *, finalize: bool) -> None:
        self.runtime.turn.unregister_context_consumer(self.CONSUMER_ID)
        tasks = tuple(task for task in (self._consume_task, *self._lanes) if task is not None)
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        self._consume_task, self._lanes = None, ()
        while not self._inference_queue.empty():
            self._discard_job(self._inference_queue.get_nowait())
        for queue in (self._identity_queue, self._attribute_queue):
            while not queue.empty():
                self._retire(queue.get_nowait())

        self._segments.clear()
        self._retired_segments.clear()
        self._shorts.clear()
        self._tracks.clear()
        self._release_tracks()
        self._profile_caches.clear()
        self._attribute_times.clear()
        self.perception_runtime.clear_observation_consumer(
            self.CONSUMER_ID, streams={PerceptionStreamKind.SPEECH}
        )
        logger.info("Persona Speaker stopped")
