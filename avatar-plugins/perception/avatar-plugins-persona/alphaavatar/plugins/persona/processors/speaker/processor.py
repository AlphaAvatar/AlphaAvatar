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
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from alphaavatar.agents.constants import SPEAKER_MATCH_THRESHOLD
from alphaavatar.agents.persona import PersonaProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import avatar_capability
from alphaavatar.agents.runtime.capability.enums import AvatarCapabilityName
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import AudioFrame, PayloadFormatUnavailable
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session.enums import IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import IdentityRequest, Participant

from ...log import logger
from ...runtime import PersonaRuntime
from .attribute_runner import SpeakerAttributeRunner
from .cache import SpeakerCache
from .config import SpeakerConfig
from .model_files import SPEAKER_MODEL_CONFIG
from .tracking import SpeakerTracks
from .vector_runner import SpeakerVectorRunner


@dataclass(slots=True)
class SpeakerSegmentState:
    segment: PerceptionSegmentRef
    entity: PerceptionEntityRef | None
    participant: Participant | None
    identities: Mapping[str, Participant]
    token: int
    pcm: bytearray = field(default_factory=bytearray)
    recent: bytearray = field(default_factory=bytearray)
    seen: set[str] = field(default_factory=set)
    seen_order: deque[str] = field(default_factory=deque)
    window_index: int = 0
    samples: int = 0
    last_window_end: int = 0
    pending: int = 0
    closed: bool = False
    invalid: bool = False
    inference_failed: bool = False
    vector: np.ndarray | None = None
    last_audio: bytes | None = None


@dataclass(slots=True, frozen=True)
class SpeakerWindow:
    state: SpeakerSegmentState
    audio_f32: bytes

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
        self._tracks = SpeakerTracks(
            threshold=config.track_match_threshold,
            margin=config.track_match_margin,
            max_tracks=config.max_speakers,
            ttl_sec=config.track_ttl_sec,
        )
        self._inference_queue: asyncio.Queue[SpeakerWindow | SpeakerSegmentState] = asyncio.Queue(
            maxsize=config.inference_queue_size
        )

        self._consume_task: asyncio.Task[None] | None = None
        self._inference_task: asyncio.Task[None] | None = None
        self._inference_job: asyncio.Task[None] | None = None
        self._active_state: SpeakerSegmentState | None = None

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

    def _is_current(self, state: SpeakerSegmentState) -> bool:
        return self._segments.get(
            state.segment
        ) is state and self.runtime.participants.segment_is_current(state.segment, state.token)

    def _retire(self, state: SpeakerSegmentState) -> None:
        if self._segments.get(state.segment) is state:
            self._segments.pop(state.segment)
        state.pcm.clear()
        state.recent.clear()
        state.last_audio = None
        state.seen.clear()
        state.seen_order.clear()
        self._retired_segments[state.segment] = None
        if len(self._retired_segments) > self.MAX_RETIRED_SEGMENTS:
            self._retired_segments.pop(next(iter(self._retired_segments)))

    def _invalidate(self, state: SpeakerSegmentState) -> None:
        state.invalid = True
        self.runtime.participants.bind_segment(state.segment, None, token=state.token)

    def _release_tracks(self) -> None:
        for source, entity in self._tracks.drain_retired():
            self.runtime.participants.release_entity(source, entity)

    def _discard_job(self, job: SpeakerWindow | SpeakerSegmentState) -> None:
        state = job.state if isinstance(job, SpeakerWindow) else job
        if isinstance(job, SpeakerWindow):
            state.pending -= 1
        if self._segments.get(state.segment) is state:
            state.inference_failed = True
            if state.closed and state.pending == 0:
                self._retire(state)

    def _enqueue(self, job: SpeakerWindow | SpeakerSegmentState) -> None:
        if self._inference_queue.full():
            self._discard_job(self._inference_queue.get_nowait())
        self._inference_queue.put_nowait(job)

    def _enqueue_pcm(self, state: SpeakerSegmentState, pcm16: bytes) -> None:
        audio = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        state.window_index += 1
        state.pending += 1
        self._enqueue(SpeakerWindow(state=state, audio_f32=audio.tobytes()))

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

        state = self._segments.get(segment)
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

            entity = observation.entity
            participant = (
                self.runtime.participants.ensure_entity(segment.source, entity)
                if entity is not None
                else None
            )
            state = SpeakerSegmentState(
                segment=segment,
                entity=entity,
                participant=participant,
                identities=self.session_runtime.snapshot().participants,
                token=self.runtime.participants.observe_segment(segment),
            )
            self._segments[segment] = state
        elif observation.entity is not None and observation.entity != state.entity:
            if state.entity is not None:
                # Conflicting explicit subjects invalidate the physical association.
                self._invalidate(state)
            else:
                state.entity = observation.entity
                existing = self.runtime.participants.resolve(
                    source=segment.source, entity=state.entity
                )
                state.participant = (
                    state.identities.get(existing.participant_id)
                    if existing is not None
                    else self.runtime.participants.ensure_entity(segment.source, state.entity)
                )

        # An explicit subject is usable before optional identity inference has completed.
        if state.entity is not None and not state.invalid:
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

        state.seen.add(observation_id)
        state.seen_order.append(observation_id)
        if len(state.seen_order) > self.MAX_SEEN_OBSERVATIONS:
            state.seen.discard(state.seen_order.popleft())

        state.samples += len(frame.data) // 2
        state.pcm.extend(frame.data)
        state.recent.extend(frame.data)
        del state.recent[: -self._window_bytes]
        while len(state.pcm) >= self._window_bytes:
            self._enqueue_pcm(state, bytes(state.pcm[: self._window_bytes]))
            state.last_window_end = state.samples - (len(state.pcm) - self._window_bytes) // 2
            del state.pcm[: self._step_bytes]

    def _close_segment(self, observation: EnvObservation) -> None:
        state = self._state(observation)
        if state is None or state.closed:
            return
        # Include the final tail in a full window; no zero-padding of short utterances.
        if (
            not state.invalid
            and not state.inference_failed
            and len(state.recent) == self._window_bytes
            and state.last_window_end != state.samples
        ):
            self._enqueue_pcm(state, bytes(state.recent))
        state.closed = True
        state.pcm.clear()
        state.recent.clear()
        if state.pending == 0:
            self._enqueue(state)

    def _cancel_source(self, source: PerceptionSourceRef) -> None:
        for state in tuple(self._segments.values()):
            if state.segment.source == source:
                self._invalidate(state)
                self._retire(state)

        self.runtime.participants.retire_source(source)
        self._tracks.clear(source)
        self._release_tracks()
        if self._active_state is not None and self._active_state.segment.source == source:
            if self._inference_job is not None:
                self._inference_job.cancel()

    async def _infer_window(self, job: SpeakerWindow) -> None:
        state = job.state
        if not self._is_current(state) or state.invalid or state.inference_failed:
            return

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

        vector = np.frombuffer(result, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(vector).all() or not np.isfinite(norm) or norm <= 0:
            raise ValueError("Speaker vector must contain finite values and have a positive norm")

        vector = vector / norm
        if state.vector is not None:
            if state.vector.shape != vector.shape:
                raise ValueError("Speaker vector shape changed within a segment")
            if float(np.dot(state.vector, vector)) < self._config.segment_consistency_threshold:
                self._invalidate(state)
                return

        if state.vector is None:
            state.vector = vector.copy()

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
                    basis_sequence=participant.identity_sequence,
                    reason=f"Speaker vector matched the stored user above {SPEAKER_MATCH_THRESHOLD}",
                )
            )
            if outcome not in (IdentityOutcome.APPLIED, IdentityOutcome.UNCHANGED):
                return None

        cache = self.persona.cache_for(participant.participant_id)
        if cache is None:
            return None

        cache.speaker_vector = state.vector.copy()
        return cache.participant

    async def _infer_attribute(self, state: SpeakerSegmentState, participant: Participant) -> None:
        if state.last_audio is None:
            return

        now = time.monotonic()
        if (
            now - self._attribute_times.get(participant.participant_id, -float("inf"))
            < self.ATTRIBUTE_INTERVAL_SEC
        ):
            return

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
            and len(self._profile_caches) >= self._config.max_speakers
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

        try:
            if state.invalid:
                return

            if state.entity is None:
                if state.vector is None or state.inference_failed:
                    return

                state.entity = self._tracks.resolve(
                    state.segment.source, state.vector, time.monotonic()
                )
                self._release_tracks()
                if state.entity is None:
                    return

                existing = self.runtime.participants.resolve(
                    source=state.segment.source, entity=state.entity
                )
                state.participant = (
                    state.identities.get(existing.participant_id)
                    if existing is not None
                    else self.runtime.participants.ensure_entity(state.segment.source, state.entity)
                )

            if not self.runtime.participants.bind_segment(
                state.segment, state.entity, token=state.token
            ):
                return

            if self.runtime.participants.resolve(segment=state.segment) is None:
                return

            participant = state.participant
            if participant is None or state.vector is None or state.inference_failed:
                return

            participant = await self._resolve_identity(state, participant)
            if participant is not None:
                await self._infer_attribute(state, participant)
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
            raise

        finally:
            if isinstance(job, SpeakerWindow):
                state.pending -= 1

            if not self._is_current(state) or (
                state.closed and state.pending == 0 and (state.invalid or state.inference_failed)
            ):
                self._retire(state)

        await self._finish_segment(state)

    async def _inference_loop(self) -> None:
        while True:
            job = await self._inference_queue.get()
            state = job.state if isinstance(job, SpeakerWindow) else job
            self._active_state = state
            self._inference_job = asyncio.create_task(
                self._process(job), name="persona_speaker_segment"
            )

            try:
                await self._inference_job
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                logger.exception(
                    "Speaker inference failed source=%s segment=%s",
                    state.segment.source,
                    state.segment.segment_id,
                )
            finally:
                self._active_state = self._inference_job = None

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

    """Runtime operations"""

    async def _start(self) -> None:
        self._inference_task = asyncio.create_task(
            self._inference_loop(), name="persona_speaker_inference"
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
        for task in (self._consume_task, self._inference_task):
            if task is not None:
                task.cancel()

        await asyncio.gather(
            *(task for task in (self._consume_task, self._inference_task) if task is not None),
            return_exceptions=True,
        )
        self._consume_task = self._inference_task = None
        while not self._inference_queue.empty():
            self._discard_job(self._inference_queue.get_nowait())

        self._segments.clear()
        self._retired_segments.clear()
        self._tracks.clear()
        self._release_tracks()
        self._profile_caches.clear()
        self._attribute_times.clear()
        self.perception_runtime.clear_observation_consumer(
            self.CONSUMER_ID, streams={PerceptionStreamKind.SPEECH}
        )
        logger.info("Persona Speaker stopped")
