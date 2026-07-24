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
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from alphaavatar.agents.avatar.voice import (
    STTBase,
    STTStreamBase,
    TranscriptionEvent,
)
from alphaavatar.agents.interaction import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import (
    AudioFrame,
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
)

from ..log import logger

TranscriptionHandler = Callable[[TranscriptionEvent], Awaitable[None] | None]


@dataclass(slots=True)
class _STTSource:
    source_id: str
    stream: STTStreamBase
    event_task: asyncio.Task[None] | None = None
    failed: bool = False


class SpeechTranscriptionProcessor(RouterProcessorBase):
    """
    Stream routed speech frames into STT.

    Audio input and provider output run independently:
    - speech consumer only performs non-blocking push/commit operations;
    - STT provider performs network inference in its own worker;
    - provider events are dispatched by one event task per source.
    """

    CONSUMER_ID = "router.speech_transcription"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        stt: STTBase,
        on_event: TranscriptionHandler,
        close_timeout_sec: float = 6.0,
    ) -> None:
        super().__init__(runtime=runtime)

        if close_timeout_sec <= 0:
            raise ValueError("close_timeout_sec must be positive")

        self.stt = stt
        self._on_event = on_event
        self._close_timeout_sec = close_timeout_sec

        self._sources: dict[str, _STTSource] = {}
        self._discarded_segments: set[tuple[str, str]] = set()
        self._consume_task: asyncio.Task[None] | None = None
        self._started = False

    @property
    def name(self) -> str:
        return "speech_transcription"

    @staticmethod
    def _segment_id(observation: EnvObservation) -> str | None:
        segment_id = observation.metadata.get("segment_id")
        return str(segment_id) if segment_id else None

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

    def _create_source(self, source_id: str) -> _STTSource:
        source = _STTSource(
            source_id=source_id,
            stream=self.stt.stream(source_id=source_id),
        )
        source.event_task = asyncio.create_task(
            self._event_loop(source),
            name=f"router_stt_events:{source_id}",
        )
        self._sources[source_id] = source

        logger.info(
            "Speech transcription source created source_id=%s provider=%s model=%s",
            source_id,
            self.stt.provider,
            self.stt.model,
        )
        return source

    async def _close_source(self, source: _STTSource, *, graceful: bool) -> None:
        if self._sources.get(source.source_id) is source:
            self._sources.pop(source.source_id, None)

        task = source.event_task

        if graceful and source.stream.end_input() and task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=self._close_timeout_sec,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Speech transcription source drain timed out source_id=%s",
                    source.source_id,
                )

        if task is not None and not task.done():
            task.cancel()

        await source.stream.aclose()

        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _replace_source(self, source_id: str) -> _STTSource:
        previous = self._sources.get(source_id)

        if previous is not None:
            await self._close_source(previous, graceful=False)

        return self._create_source(source_id)

    async def _close_sources(self, *, graceful: bool) -> None:
        sources = list(self._sources.values())
        self._sources.clear()

        for source in sources:
            await self._close_source(source, graceful=graceful)

    async def _dispatch_event(self, event: TranscriptionEvent) -> None:
        try:
            result = self._on_event(event)

            if inspect.isawaitable(result):
                await result

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Transcription event handler failed source_id=%s segment_id=%s type=%s",
                event.source_id,
                event.segment_id,
                event.type,
            )

    async def _event_loop(self, source: _STTSource) -> None:
        try:
            async for event in source.stream:
                await self._dispatch_event(event)

        except asyncio.CancelledError:
            raise
        except Exception:
            source.failed = True
            logger.exception(
                "Speech transcription stream failed source_id=%s",
                source.source_id,
            )

    async def _consume_frame(
        self,
        observation: EnvObservation,
        *,
        source_id: str,
        segment_id: str,
    ) -> None:
        segment_key = (source_id, segment_id)

        if segment_key in self._discarded_segments:
            return

        frame = self._extract_frame(observation)
        if frame is None:
            return

        source = self._sources.get(source_id)

        if source is None:
            source = self._create_source(source_id)
        elif source.failed:
            self._discarded_segments.add(segment_key)
            await self._replace_source(source_id)
            return

        if source.stream.push_frame(frame, segment_id=segment_id):
            return

        # A rejected frame makes this segment discontinuous. Do not return a
        # misleading partial transcript from the remaining frames.
        self._discarded_segments.add(segment_key)
        await self._replace_source(source_id)

        logger.warning(
            "Speech transcription discarded segment after input rejection "
            "source_id=%s segment_id=%s",
            source_id,
            segment_id,
        )

    async def _commit_segment(self, *, source_id: str, segment_id: str) -> None:
        segment_key = (source_id, segment_id)

        if segment_key in self._discarded_segments:
            self._discarded_segments.discard(segment_key)
            return

        source = self._sources.get(source_id)
        if source is None:
            logger.warning(
                "Speech transcription commit has no active source source_id=%s segment_id=%s",
                source_id,
                segment_id,
            )
            return

        if source.failed or not source.stream.commit_segment(segment_id):
            self._discarded_segments.add(segment_key)
            await self._replace_source(source_id)

            logger.warning(
                "Speech transcription failed to commit segment source_id=%s segment_id=%s",
                source_id,
                segment_id,
            )

    async def _consume_observation(self, observation: EnvObservation) -> None:
        source_id = observation.source_id
        segment_id = self._segment_id(observation)

        if not source_id or segment_id is None:
            return

        if observation.kind == "audio_frame":
            await self._consume_frame(
                observation,
                source_id=source_id,
                segment_id=segment_id,
            )
        elif observation.kind == "audio_segment":
            await self._commit_segment(
                source_id=source_id,
                segment_id=segment_id,
            )

    async def _consume_loop(self) -> None:
        while True:
            try:
                await self.perception_runtime.wait_for_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={"speech"},
                )

                window = self.perception_runtime.take_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={"speech"},
                    require_payload=True,
                )

                if window.has_gap:
                    logger.warning(
                        "Speech transcription observed input gap missed=%s",
                        window.missed_count,
                    )
                    await self._close_sources(graceful=False)
                    self._discarded_segments.clear()

                stream_read = window.stream_reads.get("speech")

                if stream_read is not None:
                    for observation in stream_read.items:
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

                self.perception_runtime.commit_observations(window)

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
            self.stt.provider,
            self.stt.model,
            self.stt.streaming,
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
        self._discarded_segments.clear()

        self.perception_runtime.clear_consumer(
            self.CONSUMER_ID,
            streams={"speech"},
        )

        logger.info("Speech transcription stopped")
