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
from collections import OrderedDict
from dataclasses import dataclass, field

from alphaavatar.agents.interaction import (
    AddressingEvidenceKind,
    AddressingMode,
    InteractionAddressingEvidence,
    InteractionEntityKind,
    InteractionEntityRef,
    InvocationDetection,
    InvocationDetectorBase,
    InvocationDetectorStreamBase,
    RouterProcessorBase,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import (
    EnvObservation,
    ObservationKind,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import (
    AudioFrame,
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
)
from alphaavatar.core.perception import PerceptionStreamKind

from ...log import logger


@dataclass(slots=True)
class _InvocationSource:
    source: PerceptionSourceRef
    stream: InvocationDetectorStreamBase
    event_task: asyncio.Task[None] | None = None


@dataclass(slots=True)
class _InvocationSegmentContext:
    speaker: InteractionEntityRef
    detected_phrase_ids: set[str] = field(default_factory=set)
    input_dropped: bool = False


class InvocationAddressingProcessor(RouterProcessorBase):
    CONSUMER_ID = "router.addressing.invocation"
    SOURCE = "router.addressing.invocation"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        detector: InvocationDetectorBase,
        evidence_confidence: float = 0.9,
        early_window_sec: float = 2.0,
        late_confidence_scale: float = 0.6,
        max_segment_contexts: int = 128,
    ) -> None:
        super().__init__(runtime=runtime)

        if not 0.0 <= evidence_confidence <= 1.0:
            raise ValueError("evidence_confidence must be between 0 and 1")
        if early_window_sec < 0:
            raise ValueError("early_window_sec cannot be negative")
        if not 0.0 <= late_confidence_scale <= 1.0:
            raise ValueError("late_confidence_scale must be between 0 and 1")
        if max_segment_contexts <= 0:
            raise ValueError("max_segment_contexts must be positive")

        self._detector = detector
        self._evidence_confidence = evidence_confidence
        self._early_window_sec = early_window_sec
        self._late_confidence_scale = late_confidence_scale
        self._max_segment_contexts = max_segment_contexts

        self._sources: dict[PerceptionSourceRef, _InvocationSource] = {}
        self._segments: OrderedDict[PerceptionSegmentRef, _InvocationSegmentContext] = OrderedDict()

        self._consume_task: asyncio.Task[None] | None = None
        self._started = False

    @property
    def name(self) -> str:
        return "invocation_addressing"

    @staticmethod
    def _frame(observation: EnvObservation) -> AudioFrame | None:
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

    @staticmethod
    def _speaker(observation: EnvObservation) -> InteractionEntityRef:
        return InteractionEntityRef(
            kind=InteractionEntityKind.PERSON,
            entity=observation.entity,
            transport_participant_id=(observation.transport_participant_id),
        )

    def _context(
        self,
        observation: EnvObservation,
    ) -> _InvocationSegmentContext:
        segment = observation.segment
        if segment is None:
            raise RuntimeError(f"{observation.kind.value} has no segment")

        context = self._segments.get(segment)

        if context is None:
            context = _InvocationSegmentContext(speaker=self._speaker(observation))
            self._segments[segment] = context

            while len(self._segments) > self._max_segment_contexts:
                self._segments.popitem(last=False)

        elif context.speaker.entity is None and observation.entity is not None:
            context.speaker = self._speaker(observation)

        self._segments.move_to_end(segment)
        return context

    def _publish_detection(self, detection: InvocationDetection) -> None:
        context = self._segments.get(detection.segment)
        if (
            context is None
            or context.input_dropped
            or detection.phrase_id in context.detected_phrase_ids
        ):
            return

        context.detected_phrase_ids.add(detection.phrase_id)

        confidence = self._evidence_confidence
        if detection.stream_offset_sec > self._early_window_sec:
            confidence *= self._late_confidence_scale

        evidence = InteractionAddressingEvidence(
            evidence_kind=AddressingEvidenceKind.INVOCATION,
            speaker=context.speaker,
            addressees=(InteractionEntityRef(kind=InteractionEntityKind.AVATAR),),
            addressing_mode=AddressingMode.DIRECT,
            confidence=confidence,
            evidence_label=detection.phrase_id,
            raw_score=detection.raw_score,
            evidence_observation_ids=(detection.observation_id,),
        )

        self._runtime.perception.publish_annotation(
            evidence.to_annotation(
                source=self.SOURCE,
                observation_id=detection.observation_id,
            )
        )

        logger.debug(
            "Invocation detected phrase_id=%s segment=%s offset=%.3f confidence=%.3f",
            detection.phrase_id,
            detection.segment.segment_id,
            detection.stream_offset_sec,
            confidence,
        )

    async def _event_loop(self, source: _InvocationSource) -> None:
        try:
            async for detection in source.stream:
                self._publish_detection(detection)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Invocation detector stream failed source_id=%s generation=%s",
                source.source.source_id,
                source.source.source_generation,
            )

    async def _create_source(
        self,
        source_ref: PerceptionSourceRef,
    ) -> _InvocationSource:
        old_sources = [
            source
            for source in self._sources.values()
            if source.source.source_id == source_ref.source_id and source.source != source_ref
        ]

        for old_source in old_sources:
            await self._close_source(old_source)

        source = _InvocationSource(
            source=source_ref,
            stream=self._detector.stream(source=source_ref),
        )
        source.event_task = asyncio.create_task(
            self._event_loop(source),
            name=(
                f"router_invocation_events:{source_ref.source_id}:{source_ref.source_generation}"
            ),
        )

        self._sources[source_ref] = source
        return source

    async def _get_source(
        self,
        source_ref: PerceptionSourceRef,
    ) -> _InvocationSource:
        source = self._sources.get(source_ref)
        return source or await self._create_source(source_ref)

    async def _close_source(self, source: _InvocationSource) -> None:
        if self._sources.get(source.source) is source:
            self._sources.pop(source.source, None)

        await source.stream.aclose()

        if source.event_task is not None:
            if not source.event_task.done():
                source.event_task.cancel()

            await asyncio.gather(
                source.event_task,
                return_exceptions=True,
            )

    async def _close_sources(self) -> None:
        sources = tuple(self._sources.values())
        self._sources.clear()

        await asyncio.gather(
            *(self._close_source(source) for source in sources),
            return_exceptions=True,
        )

    async def _consume_observation(self, observation: EnvObservation) -> None:
        segment = observation.segment
        if segment is None:
            raise RuntimeError(f"{observation.kind.value} has no segment")

        context = self._context(observation)
        source = await self._get_source(segment.source)

        if observation.kind == ObservationKind.SPEECH_FRAME:
            if context.input_dropped:
                return

            frame = self._frame(observation)
            if frame is None:
                return

            if source.stream.push_frame(
                frame,
                segment=segment,
                observation_id=observation.observation_id,
            ):
                return

            context.input_dropped = True
            logger.warning(
                "Invocation input dropped segment=%s source_id=%s generation=%s dropped_chunks=%s",
                segment.segment_id,
                segment.source.source_id,
                segment.source.source_generation,
                source.stream.dropped_chunks,
            )
            return

        if observation.kind == ObservationKind.SPEECH_SEGMENT:
            source.stream.finish_segment(segment)

    async def _consume_loop(self) -> None:
        streams = {PerceptionStreamKind.SPEECH}

        while True:
            try:
                await self._runtime.perception.wait_for_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams=streams,
                )

                window = self._runtime.perception.take_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams=streams,
                    require_payload=True,
                )

                if window.has_gap:
                    logger.warning(
                        "Invocation detector observed input gap missed=%s",
                        window.missed_count,
                    )
                    await self._close_sources()
                    self._segments.clear()

                for observation in window.speech_observations:
                    try:
                        await self._consume_observation(observation)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "Invocation detector failed observation_id=%s kind=%s",
                            observation.observation_id,
                            observation.kind,
                        )

                self._runtime.perception.commit_observations(window)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Invocation addressing consumer failed")
                await asyncio.sleep(0.05)

    async def start(self) -> None:
        if self._started:
            return

        await self._detector.start()

        self._started = True
        self._consume_task = asyncio.create_task(
            self._consume_loop(),
            name="router_invocation_addressing",
        )

        logger.info(
            "Invocation Addressing started provider=%s model=%s",
            self._detector.provider,
            self._detector.model,
        )

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False

        if self._consume_task is not None:
            self._consume_task.cancel()
            await asyncio.gather(
                self._consume_task,
                return_exceptions=True,
            )
            self._consume_task = None

        await self._close_sources()
        await self._detector.aclose()

        self._segments.clear()

        self._runtime.perception.clear_observation_consumer(
            self.CONSUMER_ID,
            streams={PerceptionStreamKind.SPEECH},
        )

        logger.info("Invocation Addressing stopped")
