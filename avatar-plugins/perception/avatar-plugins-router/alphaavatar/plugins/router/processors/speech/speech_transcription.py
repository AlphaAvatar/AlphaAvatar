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
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import uuid4

from alphaavatar.agents.avatar.voice import (
    STTBase,
    STTStreamBase,
    TranscriptionEvent,
    TranscriptionEventType,
)
from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind, SpeechCancellationReason
from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import AudioFrame, PayloadFormatUnavailable, TextPayload
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.time import RuntimeTimeRange

logger = logging.getLogger(__name__)

_ERROR_CODES = frozenset(
    (
        "empty_segment",
        "missing_audio",
        "provider_error",
        "stream_error",
        "missing_final",
        "request_queue_full",
        "request_timeout",
        "connection_error",
        "invalid_final",
        "input_flushed",
    )
)


@dataclass(slots=True)
class _SegmentState:
    time_range: RuntimeTimeRange
    device_id: str | None
    entity: PerceptionEntityRef | None
    closed: bool = False
    input_source: PerceptionSourceRef | None = None
    stream_id: str | None = None
    first_stream_sequence: int = 0
    last_stream_sequence: int = 0
    frame_count: int = 0
    duplicate_count: int = 0


@dataclass(slots=True)
class _STTSource:
    source: PerceptionSourceRef
    transcript_source: PerceptionSourceRef
    stream: STTStreamBase
    event_task: asyncio.Task[None] | None = None
    close_task: asyncio.Task[None] | None = None
    failed: bool = False
    closing: bool = False
    retired: bool = False
    stream_id: str = field(default_factory=lambda: uuid4().hex)


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
        max_pending_segments: int = 256,
        max_retired_segments: int = 1024,
        max_sources: int = 64,
    ) -> None:
        super().__init__(runtime=runtime)

        if close_timeout_sec <= 0:
            raise ValueError("close_timeout_sec must be positive")
        if min(max_pending_segments, max_retired_segments, max_sources) <= 0:
            raise ValueError("Speech transcription retention limits must be positive")

        self._stt = stt
        self._close_timeout_sec = close_timeout_sec
        self._max_pending_segments = max_pending_segments
        self._max_retired_segments = max_retired_segments
        self._max_sources = max_sources

        self._sources: dict[PerceptionSourceRef, _STTSource] = {}
        self._closing_sources: dict[str, _STTSource] = {}
        self._segments: dict[PerceptionSegmentRef, _SegmentState] = {}
        self._generations: dict[str, int] = {}
        # Cancelled producer epochs remain retired until a newer generation arrives.
        self._cancelled_generations: dict[str, int] = {}
        # Duplicate protection covers this retained window, not arbitrary historical replay.
        self._retired: OrderedDict[PerceptionSegmentRef, None] = OrderedDict()
        self._retired_evictions = 0

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
        current: RuntimeTimeRange, incoming: RuntimeTimeRange
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
                PayloadFormat.AUDIO_FRAME, view=PayloadView.RAW, fallback_to_raw=False
            )
        except PayloadFormatUnavailable:
            return None

        return frame if isinstance(frame, AudioFrame) else None

    @staticmethod
    def _input_source(observation: EnvObservation) -> PerceptionSourceRef | None:
        value = observation.metadata.get("input_source")
        if not isinstance(value, Mapping):
            return None
        source_id, generation = value.get("source_id"), value.get("source_generation")
        if not isinstance(source_id, str) or not source_id:
            return None
        if type(generation) is not int or generation <= 0:
            return None
        return PerceptionSourceRef(source_id=source_id, source_generation=generation)

    def _record(
        self,
        stage: str,
        *,
        segment: PerceptionSegmentRef | None = None,
        state: _SegmentState | None = None,
        source: _STTSource | None = None,
        **fields: object,
    ) -> None:
        source_ref = segment.source if segment is not None else source.source if source else None
        values: dict[str, object] = {}
        if source_ref is not None:
            values.update(
                source_id=source_ref.source_id, source_generation=source_ref.source_generation
            )
        if segment is not None:
            values["segment_id"] = segment.segment_id
        if source is not None:
            values["stream_id"] = source.stream_id
        if state is not None:
            values.update(
                stream_id=state.stream_id,
                first_stream_sequence=state.first_stream_sequence,
                last_stream_sequence=state.last_stream_sequence,
                frame_count=state.frame_count,
                duplicate_count=state.duplicate_count,
            )
            if state.input_source is not None:
                values.update(
                    input_source_id=state.input_source.source_id,
                    input_source_generation=state.input_source.source_generation,
                )
        values.update(fields)
        self._runtime.perception.input_trace.record(stage, **values)

    def _finish_segment(
        self, segment: PerceptionSegmentRef, *, outcome: str, reason: str, **fields: object
    ) -> None:
        if segment in self._retired:
            return
        state = self._segments.pop(segment, None)
        self._retired[segment] = None
        if len(self._retired) > self._max_retired_segments:
            self._retired.popitem(last=False)
            self._retired_evictions += 1
        self._record(
            "stt.terminal",
            segment=segment,
            state=state,
            outcome=outcome,
            reason=reason,
            retired_evictions=self._retired_evictions,
            **fields,
        )

    def _finish_source_segments(self, source: _STTSource, *, outcome: str, reason: str) -> None:
        for segment, state in tuple(self._segments.items()):
            if segment.source == source.source and state.stream_id == source.stream_id:
                self._finish_segment(segment, outcome=outcome, reason=reason)

    async def _accept_generation(self, segment: PerceptionSegmentRef) -> bool:
        source_ref = segment.source
        generation = self._generations.get(source_ref.source_id)
        if generation is not None and source_ref.source_generation < generation:
            self._finish_segment(segment, outcome="stale", reason="source_generation_retired")
            return False
        if self._cancelled_generations.get(source_ref.source_id) == source_ref.source_generation:
            self._finish_segment(segment, outcome="stale", reason="source_generation_retired")
            return False
        if generation is None and len(self._generations) >= self._max_sources:
            self._finish_segment(segment, outcome="rejected", reason="source_capacity")
            self._runtime.perception.input_trace.freeze(reason="source_capacity")
            return False
        if generation != source_ref.source_generation:
            self._generations[source_ref.source_id] = source_ref.source_generation
            self._cancelled_generations.pop(source_ref.source_id, None)
            for current in tuple(self._sources.values()):
                if (
                    current.source.source_id == source_ref.source_id
                    and current.source != source_ref
                ):
                    await self._close_source(
                        current, graceful=False, reason="source_generation_retired"
                    )
        return True

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
        self._record("stt.source_started", source=source, outcome="open")

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
        self, observation: EnvObservation
    ) -> tuple[PerceptionSegmentRef, _SegmentState] | None:
        segment = observation.segment
        if segment is None:
            return None

        state = self._segments.get(segment)
        if state is None:
            state = _SegmentState(
                time_range=observation.time_range,
                device_id=observation.device_id,
                entity=observation.entity,
                input_source=self._input_source(observation),
            )
            self._segments[segment] = state
        else:
            state.time_range = self._merge_time_range(state.time_range, observation.time_range)
            # Conflicting provenance disables external forwarding, not internal recognition.
            if state.input_source != self._input_source(observation):
                state.input_source = None

            if observation.device_id is not None:
                state.device_id = observation.device_id
            if observation.entity is not None:
                state.entity = observation.entity

        return segment, state

    async def _close_source(
        self, source: _STTSource, *, graceful: bool, reason: str = "source_closed"
    ) -> None:
        if source.close_task is not None:
            return
        source.closing = True
        if not graceful:
            source.retired = True
            self._finish_source_segments(source, outcome="cancelled", reason=reason)
        if self._sources.get(source.source) is source:
            self._sources.pop(source.source, None)
        self._closing_sources[source.stream_id] = source
        source.close_task = asyncio.create_task(
            self._cleanup_source(source, graceful=graceful, reason=reason),
            name=f"router_stt_close:{source.source.source_id}:{source.stream_id}",
        )
        source.close_task.add_done_callback(lambda task: self._observe_close(source, task))

    def _observe_close(self, source: _STTSource, task: asyncio.Task[None]) -> None:
        self._closing_sources.pop(source.stream_id, None)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Speech transcription source cleanup failed", exc_info=error)

    async def _cleanup_source(self, source: _STTSource, *, graceful: bool, reason: str) -> None:
        task = source.event_task
        deadline = asyncio.get_running_loop().time() + self._close_timeout_sec
        try:
            # One deadline covers draining and closing; other sources keep consuming meanwhile.
            try:
                async with asyncio.timeout_at(deadline):
                    if graceful:
                        source.stream.end_input()
                        if task is not None:
                            await asyncio.shield(task)
            finally:
                source.retired = True
                if task is not None and not task.done():
                    task.cancel()
                async with asyncio.timeout_at(deadline):
                    await source.stream.aclose()
                    if task is not None:
                        await asyncio.gather(task, return_exceptions=True)
        except TimeoutError:
            reason = "close_timeout"
            self._record("stt.error", source=source, reason=reason)
            self._runtime.perception.input_trace.freeze(reason="stt_close_timeout")
        except asyncio.CancelledError:
            reason = "close_cancelled"
            raise
        except Exception:
            reason = "close_error"
            self._record("stt.error", source=source, reason=reason)
            self._runtime.perception.input_trace.freeze(reason="stt_close_error")
            logger.exception("Speech transcription source cleanup failed")
        finally:
            source.retired = True
            if task is not None and not task.done():
                task.cancel()
            self._finish_source_segments(source, outcome="closed_without_final", reason=reason)
            self._record("stt.source_closed", source=source, outcome="closed", reason=reason)

    async def _get_source(self, source_ref: PerceptionSourceRef) -> _STTSource | None:
        source = self._sources.get(source_ref)
        if source is not None and (source.failed or source.retired):
            await self._close_source(source, graceful=False, reason="stream_error")
            source = None
        if source is None and len(self._sources) + len(self._closing_sources) >= self._max_sources:
            return None
        return source if source is not None else self._create_source(source_ref)

    async def _close_sources(self, *, graceful: bool, reason: str = "source_closed") -> None:
        for source in tuple(self._sources.values()):
            await self._close_source(source, graceful=graceful, reason=reason)
        if graceful and self._closing_sources:
            tasks = tuple(source.close_task for source in self._closing_sources.values())
            _, pending = await asyncio.wait(tasks, timeout=self._close_timeout_sec)
            if pending:
                self._record("stt.error", reason="close_timeout")
                self._runtime.perception.input_trace.freeze(reason="stt_close_timeout")
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=min(0.05, self._close_timeout_sec))

    def _publish_transcription_observation(
        self,
        *,
        source: _STTSource,
        segment: PerceptionSegmentRef,
        state: _SegmentState,
        event: TranscriptionEvent,
    ) -> tuple[str, int | None] | None:
        text = event.text.strip()
        if not text:
            return None

        metadata: dict[str, object] = {
            "language": event.language,
            "confidence": event.confidence,
            "provider": event.provider,
            "model": event.model,
        }
        if state.input_source is not None:
            metadata["input_source"] = state.input_source.to_dict()

        payload = TextPayload.create(text=text, language=event.language, metadata=dict(metadata))

        factory = (
            EnvObservation.transcript_segment
            if event.type == TranscriptionEventType.FINAL_TRANSCRIPT
            else EnvObservation.transcript_delta
        )

        observation = factory(
            time_range=state.time_range,
            source=source.transcript_source,
            segment=segment,
            device_id=state.device_id,
            entity=state.entity,
            payload=payload,
            metadata=metadata,
        )
        published = self._runtime.perception.publish_observation(observation)
        return observation.observation_id, published.sequence if published is not None else None

    async def _dispatch_event(self, source: _STTSource, event: TranscriptionEvent) -> None:
        segment = PerceptionSegmentRef(source=source.source, segment_id=event.segment_id)
        current = (
            self._sources.get(source.source) is source
            or self._closing_sources.get(source.stream_id) is source
        )
        if source.retired or not current:
            self._record("stt.stale", segment=segment, source=source, reason="stream_retired")
            return
        if event.source_id != source.source.source_id:
            self._record("stt.stale", segment=segment, source=source, reason="source_mismatch")
            return

        reason = event.reason_code if event.reason_code in _ERROR_CODES else "provider_error"
        if event.type == TranscriptionEventType.ERROR and event.segment_id == "unknown":
            source.failed = True
            self._finish_source_segments(source, outcome="error", reason=reason)
            self._record("stt.error", source=source, reason=reason)
            self._runtime.perception.input_trace.freeze(reason="stt_stream_error")
            return

        state = self._segments.get(segment)
        if state is None or state.stream_id != source.stream_id or source.failed:
            self._record("stt.stale", segment=segment, source=source, reason="segment_retired")
            return

        if event.type == TranscriptionEventType.ERROR:
            self._finish_segment(
                segment,
                outcome="cancelled" if reason == "input_flushed" else "error",
                reason=reason,
                provider_item_id=event.provider_item_id,
            )
            if reason != "input_flushed":
                self._runtime.perception.input_trace.freeze(reason="stt_segment_error")
            return
        if event.type not in {
            TranscriptionEventType.INTERIM_TRANSCRIPT,
            TranscriptionEventType.FINAL_TRANSCRIPT,
        }:
            return

        published = self._publish_transcription_observation(
            source=source, segment=segment, state=state, event=event
        )
        if event.type == TranscriptionEventType.FINAL_TRANSCRIPT:
            self._finish_segment(
                segment,
                outcome="final_text" if published else "final_empty",
                reason="provider_final",
                text_chars=len(event.text.strip()),
                provider_item_id=event.provider_item_id,
                observation_id=published[0] if published else None,
                sequence=published[1] if published else None,
            )
            if published is None:
                self._runtime.perception.input_trace.freeze(reason="stt_final_empty")

    async def _event_loop(self, source: _STTSource) -> None:
        try:
            async for event in source.stream:
                await self._dispatch_event(source, event)
        except asyncio.CancelledError:
            raise
        except Exception:
            source.failed = True
            self._finish_source_segments(source, outcome="error", reason="stream_error")
            self._record("stt.error", source=source, reason="stream_error")
            self._runtime.perception.input_trace.freeze(reason="stt_stream_error")
            logger.exception(
                "Speech transcription stream failed source=%s generation=%s",
                source.source.source_id,
                source.source.source_generation,
            )
        else:
            source.failed = not source.closing
            self._finish_source_segments(
                source, outcome="closed_without_final", reason="missing_final"
            )
        finally:
            source.retired = True

    async def _consume_frame(
        self, observation: EnvObservation, *, segment: PerceptionSegmentRef, state: _SegmentState
    ) -> None:
        frame = self._extract_frame(observation)
        if frame is None:
            self._finish_segment(segment, outcome="rejected", reason="missing_frame_payload")
            source = self._sources.get(segment.source)
            if source is not None:
                await self._close_source(source, graceful=False, reason="missing_frame_payload")
            return

        source = await self._get_source(segment.source)
        if source is None:
            self._finish_segment(segment, outcome="rejected", reason="source_cleanup_capacity")
            self._runtime.perception.input_trace.freeze(reason="stt_source_cleanup_capacity")
            return
        state.stream_id = source.stream_id
        if source.stream.push_frame(frame, segment_id=segment.segment_id):
            state.frame_count += 1
            if state.frame_count == 1:
                self._record(
                    "speech.start",
                    segment=segment,
                    state=state,
                    observation_id=observation.observation_id,
                )
            return
        self._finish_segment(segment, outcome="rejected", reason="input_rejected")
        self._runtime.perception.input_trace.freeze(reason="stt_input_rejected")
        await self._close_source(source, graceful=False, reason="input_rejected")

    async def _commit_segment(self, segment: PerceptionSegmentRef, state: _SegmentState) -> None:
        source = self._sources.get(segment.source)
        if source is None or state.stream_id != source.stream_id or not state.frame_count:
            self._finish_segment(segment, outcome="rejected", reason="missing_audio")
            return

        if source.failed or not source.stream.commit_segment(segment.segment_id):
            self._finish_segment(segment, outcome="rejected", reason="commit_rejected")
            self._runtime.perception.input_trace.freeze(reason="stt_commit_rejected")
            await self._close_source(source, graceful=False, reason="commit_rejected")
            return
        self._record("stt.commit", segment=segment, state=state, outcome="accepted")

    async def _consume_observation(
        self, observation: EnvObservation, *, stream_sequence: int = 0
    ) -> None:
        segment = observation.segment
        if segment is None or observation.kind not in {
            ObservationKind.SPEECH_FRAME,
            ObservationKind.SPEECH_SEGMENT,
            ObservationKind.SPEECH_CANCELLED,
        }:
            return

        if observation.kind == ObservationKind.SPEECH_CANCELLED:
            if not await self._accept_generation(segment):
                return
            reason = SpeechCancellationReason(observation.metadata["reason_code"]).value
            self._cancelled_generations[segment.source.source_id] = segment.source.source_generation
            state = self._segments.get(segment)
            if state is not None:
                state.last_stream_sequence = stream_sequence
            input_source = self._input_source(observation) or (
                state.input_source if state else None
            )
            self._finish_segment(
                segment,
                outcome="cancelled",
                reason=reason,
                observation_id=observation.observation_id,
                stream_sequence=stream_sequence,
                input_source_id=input_source.source_id if input_source is not None else None,
                input_source_generation=(
                    input_source.source_generation if input_source is not None else None
                ),
            )
            # A cancelled producer epoch cannot share its remote PCM buffer with its successor.
            source = self._sources.get(segment.source)
            if source is not None:
                await self._close_source(source, graceful=False, reason=reason)
            return
        if segment in self._retired or not await self._accept_generation(segment):
            return
        state = self._segments.get(segment)
        if state is not None and state.closed:
            state.duplicate_count += 1
            return
        if observation.kind == ObservationKind.SPEECH_FRAME:
            route_index = observation.metadata.get("route_index")
            if type(route_index) is not int or route_index <= 0:
                self._finish_segment(segment, outcome="rejected", reason="invalid_route_index")
                source = self._sources.get(segment.source)
                if source is not None:
                    await self._close_source(source, graceful=False, reason="invalid_route_index")
                return
            if state is not None and route_index <= state.frame_count:
                state.duplicate_count += 1
                return
            if state is None and (
                route_index != 1 or observation.metadata.get("speech_event") != "start"
            ):
                self._finish_segment(segment, outcome="rejected", reason="missing_segment_start")
                return
            if state is not None and route_index != state.frame_count + 1:
                self._finish_segment(segment, outcome="rejected", reason="frame_gap")
                self._runtime.perception.input_trace.freeze(reason="stt_frame_gap")
                source = self._sources.get(segment.source)
                if source is not None:
                    await self._close_source(source, graceful=False, reason="frame_gap")
                return
        elif state is None:
            self._finish_segment(segment, outcome="rejected", reason="missing_segment_start")
            return
        if state is None and len(self._segments) >= self._max_pending_segments:
            self._finish_segment(segment, outcome="rejected", reason="pending_capacity")
            self._runtime.perception.input_trace.freeze(reason="stt_pending_capacity")
            return
        current = self._update_segment(observation)
        if current is None:
            return

        segment, state = current
        if not state.first_stream_sequence:
            state.first_stream_sequence = stream_sequence
        state.last_stream_sequence = stream_sequence

        if observation.kind == ObservationKind.SPEECH_FRAME:
            await self._consume_frame(observation, segment=segment, state=state)
            return

        if observation.kind == ObservationKind.SPEECH_SEGMENT:
            state.time_range = observation.time_range
            state.closed = True
            self._record(
                "speech.close",
                segment=segment,
                state=state,
                observation_id=observation.observation_id,
            )
            await self._commit_segment(segment, state)

    async def _consume_loop(self) -> None:
        stream = self._runtime.perception.speech
        while True:
            try:
                await stream.wait_for_pending(consumer_id=self.CONSUMER_ID)
                batch = stream.read_pending(consumer_id=self.CONSUMER_ID)
                if batch.has_gap:
                    self._record(
                        "speech.gap",
                        missed_count=batch.missed_count,
                        stream_sequence=batch.cursor_seq,
                    )
                    self._runtime.perception.input_trace.freeze(reason="speech_input_gap")
                    await self._close_sources(graceful=False, reason="input_gap")
                    for segment in tuple(self._segments):
                        self._finish_segment(segment, outcome="cancelled", reason="input_gap")

                # This unfiltered single-stream read preserves the producer's frame/close protocol.
                first_sequence = batch.cursor_seq - len(batch.items) + 1
                for sequence, observation in enumerate(batch.items, start=first_sequence):
                    try:
                        await self._consume_observation(observation, stream_sequence=sequence)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        segment = observation.segment
                        if segment is not None:
                            self._finish_segment(
                                segment, outcome="error", reason="processing_error"
                            )
                            source = self._sources.get(segment.source)
                            if source is not None:
                                await self._close_source(
                                    source, graceful=False, reason="processing_error"
                                )
                        self._runtime.perception.input_trace.freeze(reason="stt_processing_error")
                        logger.exception(
                            "Speech transcription failed to process observation "
                            "observation_id=%s kind=%s",
                            observation.observation_id,
                            observation.kind,
                        )

                stream.commit(consumer_id=self.CONSUMER_ID, cursor_seq=batch.cursor_seq)

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
            self._consume_loop(), name="router_speech_transcription"
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

        await self._close_sources(graceful=True, reason="shutdown")
        for segment in tuple(self._segments):
            self._finish_segment(segment, outcome="cancelled", reason="shutdown")
        self._runtime.perception.speech.clear_consumer(self.CONSUMER_ID)

        logger.info("Speech transcription stopped")
