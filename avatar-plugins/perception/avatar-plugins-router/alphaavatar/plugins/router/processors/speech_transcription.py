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
from dataclasses import dataclass

from alphaavatar.agents.avatar.voice import (
    STTBase,
    STTStreamBase,
    TranscriptionEvent,
    TranscriptionEventType,
)
from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import (
    EnvObservation,
    ObservationKind,
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import (
    AudioFrame,
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
    TextPayload,
)
from alphaavatar.core.perception import PerceptionStreamKind
from alphaavatar.core.time import RuntimeTimeRange

from ..log import logger


@dataclass(slots=True)
class _SegmentState:
    time_range: RuntimeTimeRange
    transport_participant_id: str | None
    entity: PerceptionEntityRef | None
    closed: bool = False
    discarded: bool = False


@dataclass(slots=True)
class _STTSource:
    source: PerceptionSourceRef
    transcript_source: PerceptionSourceRef
    stream: STTStreamBase
    event_task: asyncio.Task[None] | None = None
    failed: bool = False


class SpeechTranscriptionProcessor(RouterProcessorBase):
    """
    Stream routed speech frames into STT.

    Audio input and provider output run independently:
    - speech consumption only pushes frames and commits segments;
    - provider inference runs in its own stream;
    - provider events are dispatched by one task per perception source.
    """

    CONSUMER_ID = "router.speech_transcription"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        stt: STTBase,
        close_timeout_sec: float = 6.0,
    ) -> None:
        super().__init__(runtime=runtime)

        if close_timeout_sec <= 0:
            raise ValueError("close_timeout_sec must be positive")

        self._stt = stt
        self._close_timeout_sec = close_timeout_sec

        self._sources: dict[PerceptionSourceRef, _STTSource] = {}
        self._segments: dict[PerceptionSegmentRef, _SegmentState] = {}

        self._consume_task: asyncio.Task[None] | None = None
        self._started = False

    @property
    def name(self) -> str:
        return "speech_transcription"

    @staticmethod
    def _transcript_source_id(source_id: str) -> str:
        return f"router:transcript:{source_id}"

    @staticmethod
    def _merge_time_range(
        current: RuntimeTimeRange,
        incoming: RuntimeTimeRange,
    ) -> RuntimeTimeRange:
        start = (
            current.start
            if current.start.monotonic_ns <= incoming.start.monotonic_ns
            else incoming.start
        )
        end = current.end if current.end.monotonic_ns >= incoming.end.monotonic_ns else incoming.end
        return RuntimeTimeRange(start=start, end=end)

    @staticmethod
    def _extract_frame(observation: EnvObservation) -> AudioFrame | None:
        if observation.payload is None:
            return None

        try:
            frame = observation.payload.get(
                PayloadFormat.AUDIO_FRAME,
                view=PayloadView.RAW,
                fallback_to_raw=False,
            )
        except PayloadFormatUnavailable:
            return None

        return frame if isinstance(frame, AudioFrame) else None

    def _create_source(self, source_ref: PerceptionSourceRef) -> _STTSource:
        transcript_source = self._runtime.perception.next_source(
            self._transcript_source_id(source_ref.source_id)
        )
        source = _STTSource(
            source=source_ref,
            transcript_source=transcript_source,
            stream=self._stt.stream(source_id=source_ref.source_id),
        )
        source.event_task = asyncio.create_task(
            self._event_loop(source),
            name=f"router_stt_events:{source_ref.source_id}:{source_ref.source_generation}",
        )
        self._sources[source_ref] = source

        logger.info(
            "Speech transcription source created source=%s generation=%s "
            "transcript_generation=%s provider=%s model=%s",
            source_ref.source_id,
            source_ref.source_generation,
            transcript_source.source_generation,
            self._stt.provider,
            self._stt.model,
        )
        return source

    def _update_segment(
        self,
        observation: EnvObservation,
    ) -> tuple[PerceptionSegmentRef, _SegmentState] | None:
        segment = observation.segment
        if segment is None:
            return None

        state = self._segments.get(segment)
        if state is None:
            state = _SegmentState(
                time_range=observation.time_range,
                transport_participant_id=observation.transport_participant_id,
                entity=observation.entity,
            )
            self._segments[segment] = state
        else:
            state.time_range = self._merge_time_range(state.time_range, observation.time_range)

            if observation.transport_participant_id is not None:
                state.transport_participant_id = observation.transport_participant_id
            if observation.entity is not None:
                state.entity = observation.entity

        return segment, state

    def _clear_source_segments(self, source_ref: PerceptionSourceRef) -> None:
        for segment in tuple(self._segments):
            if segment.source == source_ref:
                self._segments.pop(segment, None)

    def _invalidate_source_segments(self, source_ref: PerceptionSourceRef) -> None:
        for segment, state in tuple(self._segments.items()):
            if segment.source != source_ref:
                continue

            if state.closed:
                self._segments.pop(segment, None)
            else:
                state.discarded = True

    async def _close_source(self, source: _STTSource, *, graceful: bool) -> None:
        if self._sources.get(source.source) is source:
            self._sources.pop(source.source, None)

        task = source.event_task

        if graceful and source.stream.end_input() and task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=self._close_timeout_sec,
                )
            except TimeoutError:
                logger.warning(
                    "Speech transcription source drain timed out source=%s generation=%s",
                    source.source.source_id,
                    source.source.source_generation,
                )

        if task is not None and not task.done():
            task.cancel()

        await source.stream.aclose()

        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _replace_source(self, source_ref: PerceptionSourceRef) -> _STTSource:
        previous = self._sources.get(source_ref)

        if previous is not None:
            self._invalidate_source_segments(source_ref)
            await self._close_source(previous, graceful=False)

        return self._create_source(source_ref)

    async def _get_source(self, source_ref: PerceptionSourceRef) -> _STTSource:
        # A new source generation retires the previous generation for the same
        # logical source. Different generations must never share an STT stream.
        for current_ref, current in tuple(self._sources.items()):
            if current_ref.source_id != source_ref.source_id or current_ref == source_ref:
                continue

            await self._close_source(current, graceful=False)
            self._clear_source_segments(current_ref)

        source = self._sources.get(source_ref)
        return source if source is not None else self._create_source(source_ref)

    async def _close_sources(self, *, graceful: bool) -> None:
        sources = list(self._sources.values())
        self._sources.clear()

        for source in sources:
            await self._close_source(source, graceful=graceful)

    def _publish_transcription_observation(
        self,
        *,
        source: _STTSource,
        segment: PerceptionSegmentRef,
        state: _SegmentState,
        event: TranscriptionEvent,
    ) -> None:
        text = event.text.strip()
        if not text:
            return

        metadata = {
            "language": event.language,
            "confidence": event.confidence,
            "provider": event.provider,
            "model": event.model,
        }
        payload = TextPayload.create(
            text=text,
            language=event.language,
            metadata=dict(metadata),
        )

        factory = (
            EnvObservation.transcript_segment
            if event.type == TranscriptionEventType.FINAL_TRANSCRIPT
            else EnvObservation.transcript_delta
        )

        self._runtime.perception.publish_observation(
            factory(
                time_range=state.time_range,
                source=source.transcript_source,
                segment=segment,
                transport_participant_id=state.transport_participant_id,
                entity=state.entity,
                payload=payload,
                metadata=metadata,
            )
        )

    async def _dispatch_event(
        self,
        source: _STTSource,
        event: TranscriptionEvent,
    ) -> None:
        segment = PerceptionSegmentRef(
            source=source.source,
            segment_id=event.segment_id,
        )
        state = self._segments.get(segment)

        if event.type in {
            TranscriptionEventType.INTERIM_TRANSCRIPT,
            TranscriptionEventType.FINAL_TRANSCRIPT,
        }:
            if state is None:
                logger.debug(
                    "Ignored stale transcription event "
                    "source=%s generation=%s segment_id=%s type=%s",
                    source.source.source_id,
                    source.source.source_generation,
                    segment.segment_id,
                    event.type,
                )
            elif not state.discarded:
                self._publish_transcription_observation(
                    source=source,
                    segment=segment,
                    state=state,
                    event=event,
                )

        if event.type in {
            TranscriptionEventType.FINAL_TRANSCRIPT,
            TranscriptionEventType.ERROR,
        }:
            self._segments.pop(segment, None)

    async def _event_loop(self, source: _STTSource) -> None:
        try:
            async for event in source.stream:
                await self._dispatch_event(source, event)
        except asyncio.CancelledError:
            raise
        except Exception:
            source.failed = True
            logger.exception(
                "Speech transcription stream failed source=%s generation=%s",
                source.source.source_id,
                source.source.source_generation,
            )

    async def _consume_frame(
        self,
        observation: EnvObservation,
        *,
        segment: PerceptionSegmentRef,
        state: _SegmentState,
    ) -> None:
        if state.discarded:
            return

        frame = self._extract_frame(observation)
        if frame is None:
            return

        source = await self._get_source(segment.source)

        if source.failed:
            state.discarded = True
            await self._replace_source(segment.source)
            return

        if source.stream.push_frame(frame, segment_id=segment.segment_id):
            return

        state.discarded = True
        await self._replace_source(segment.source)

        logger.warning(
            "Speech transcription discarded segment after input rejection "
            "source=%s generation=%s segment_id=%s",
            segment.source.source_id,
            segment.source.source_generation,
            segment.segment_id,
        )

    async def _commit_segment(
        self,
        segment: PerceptionSegmentRef,
        state: _SegmentState,
    ) -> None:
        if state.discarded:
            self._segments.pop(segment, None)
            return

        source = self._sources.get(segment.source)
        if source is None:
            logger.warning(
                "Speech transcription commit has no active source "
                "source=%s generation=%s segment_id=%s",
                segment.source.source_id,
                segment.source.source_generation,
                segment.segment_id,
            )
            self._segments.pop(segment, None)
            return

        if source.failed or not source.stream.commit_segment(segment.segment_id):
            state.discarded = True
            await self._replace_source(segment.source)

            logger.warning(
                "Speech transcription failed to commit segment "
                "source=%s generation=%s segment_id=%s",
                segment.source.source_id,
                segment.source.source_generation,
                segment.segment_id,
            )

    async def _consume_observation(self, observation: EnvObservation) -> None:
        current = self._update_segment(observation)
        if current is None:
            return

        segment, state = current

        if observation.kind == ObservationKind.SPEECH_FRAME:
            await self._consume_frame(
                observation,
                segment=segment,
                state=state,
            )
            return

        if observation.kind == ObservationKind.SPEECH_SEGMENT:
            state.time_range = observation.time_range
            state.closed = True
            await self._commit_segment(segment, state)

    async def _consume_loop(self) -> None:
        while True:
            try:
                await self._runtime.perception.wait_for_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={PerceptionStreamKind.SPEECH},
                )

                window = self._runtime.perception.take_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={PerceptionStreamKind.SPEECH},
                    require_payload=True,
                )

                if window.has_gap:
                    logger.warning(
                        "Speech transcription observed input gap missed=%s",
                        window.missed_count,
                    )
                    await self._close_sources(graceful=False)
                    self._segments.clear()

                for observation in window.speech_observations:
                    try:
                        await self._consume_observation(observation)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "Speech transcription failed to process observation "
                            "observation_id=%s kind=%s",
                            observation.observation_id,
                            observation.kind,
                        )

                self._runtime.perception.commit_observations(window)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Speech transcription consumer failed")
                await asyncio.sleep(0.05)

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        self._consume_task = asyncio.create_task(
            self._consume_loop(),
            name="router_speech_transcription",
        )

        logger.info(
            "Speech transcription started provider=%s model=%s streaming=%s",
            self._stt.provider,
            self._stt.model,
            self._stt.streaming,
        )

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False

        if self._consume_task is not None:
            self._consume_task.cancel()
            await asyncio.gather(self._consume_task, return_exceptions=True)
            self._consume_task = None

        await self._close_sources(graceful=True)
        self._segments.clear()

        self._runtime.perception.clear_observation_consumer(
            self.CONSUMER_ID,
            streams={PerceptionStreamKind.SPEECH},
        )

        logger.info("Speech transcription stopped")
