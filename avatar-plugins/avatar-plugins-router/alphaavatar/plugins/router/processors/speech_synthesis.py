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
"""Output speech synthesis processor."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from alphaavatar.agents.avatar.voice import TTSBase
from alphaavatar.agents.interaction import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.output import (
    OutputControl,
    OutputControlType,
    OutputEvent,
    OutputKind,
    OutputLane,
    OutputSubscription,
    OutputTextChunk,
    OutputTextMode,
)

from ..log import logger


@dataclass(frozen=True, slots=True)
class _SpeechSegment:
    text: str
    source_chunk_id: str | None
    is_final: bool
    metadata: dict


@dataclass(slots=True)
class _SpeechJob:
    output_id: str
    lane: OutputLane
    turn_id: str | None
    queue: asyncio.Queue[_SpeechSegment]
    task: asyncio.Task[None]


class SpeechSynthesisProcessor(RouterProcessorBase):
    """
    Convert AUDIO_SYNCED source text into normalized audio-frame output.

    One output_id owns one synthesis job. Source chunks sharing the same
    output_id are synthesized sequentially.
    """

    CONSUMER_ID = "router.speech_synthesis"
    MAX_PENDING_SEGMENTS = 64

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        tts: TTSBase | None,
        lanes: tuple[OutputLane, ...] = (OutputLane.TRANSIENT,),
    ) -> None:
        self._runtime = runtime
        self._tts = tts
        self._lanes = lanes
        self._subscription: OutputSubscription | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._jobs: dict[str, _SpeechJob] = {}
        self._started = False

    @property
    def name(self) -> str:
        return "speech_synthesis"

    async def start(self) -> None:
        if self._started:
            return

        self._subscription = await self._runtime.output.stream.subscribe(
            self.CONSUMER_ID,
            kinds=(OutputKind.TEXT_CHUNK, OutputKind.SPEECH_REQUEST, OutputKind.CONTROL),
            lanes=self._lanes,
            max_pending=128,
            reliable=True,
        )
        self._run_task = asyncio.create_task(self._run(), name=self.CONSUMER_ID)
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False
        run_task = self._run_task
        self._run_task = None

        if run_task is not None and not run_task.done():
            run_task.cancel()
        if run_task is not None:
            await asyncio.gather(run_task, return_exceptions=True)

        jobs = tuple(self._jobs.values())
        self._jobs.clear()

        for job in jobs:
            if not job.task.done():
                job.task.cancel()

        if jobs:
            await asyncio.gather(*(job.task for job in jobs), return_exceptions=True)

        if self._subscription is not None:
            await self._runtime.output.stream.unsubscribe(self.CONSUMER_ID)

        self._subscription = None

    async def _run(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return

        try:
            while True:
                event = await subscription.get()

                try:
                    if event.kind == OutputKind.TEXT_CHUNK:
                        await self._handle_text_chunk(event)
                    elif event.kind == OutputKind.SPEECH_REQUEST:
                        await self._handle_legacy_speech_request(event)
                    elif event.kind == OutputKind.CONTROL:
                        await self._handle_control(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Failed to process speech synthesis event event_id=%s output_id=%s kind=%s",
                        event.event_id,
                        event.output_id,
                        event.kind,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Speech synthesis processor stopped unexpectedly.")

    async def _handle_text_chunk(self, event: OutputEvent) -> None:
        payload = event.payload
        if not isinstance(payload, OutputTextChunk):
            return
        if payload.mode != OutputTextMode.AUDIO_SYNCED:
            return

        await self._enqueue_segment(
            event,
            _SpeechSegment(
                text=payload.text,
                source_chunk_id=payload.chunk_id,
                is_final=payload.is_final,
                metadata=dict(event.metadata),
            ),
        )

    async def _handle_legacy_speech_request(self, event: OutputEvent) -> None:
        payload = event.payload
        if not isinstance(payload, dict):
            return

        text = payload.get("text")
        if not isinstance(text, str):
            return

        await self._enqueue_segment(
            event,
            _SpeechSegment(
                text=text,
                source_chunk_id=payload.get("chunk_id"),
                is_final=bool(payload.get("is_final", True)),
                metadata=dict(event.metadata),
            ),
        )

    async def _enqueue_segment(self, event: OutputEvent, segment: _SpeechSegment) -> None:
        output_id = event.output_id
        if not output_id or not self._runtime.output.is_active(output_id):
            return

        if self._tts is None:
            await self._runtime.output.interrupt(
                lane=event.lane,
                output_id=output_id,
                reason="tts_unavailable",
            )
            return

        job = self._jobs.get(output_id)
        if job is None:
            queue: asyncio.Queue[_SpeechSegment] = asyncio.Queue(maxsize=self.MAX_PENDING_SEGMENTS)
            task = asyncio.create_task(
                self._run_job(
                    output_id=output_id,
                    lane=event.lane,
                    turn_id=event.turn_id,
                    queue=queue,
                ),
                name=f"speech_synthesis:{output_id}",
            )
            job = _SpeechJob(
                output_id=output_id,
                lane=event.lane,
                turn_id=event.turn_id,
                queue=queue,
                task=task,
            )
            self._jobs[output_id] = job
        elif job.lane != event.lane or job.turn_id != event.turn_id:
            raise ValueError(f"Speech synthesis identity mismatch output_id={output_id!r}")

        try:
            job.queue.put_nowait(segment)
        except asyncio.QueueFull:
            logger.warning(
                "Speech synthesis queue full output_id=%s max_pending=%s",
                output_id,
                self.MAX_PENDING_SEGMENTS,
            )
            await self._runtime.output.interrupt(
                lane=event.lane,
                output_id=output_id,
                reason="speech_synthesis_queue_full",
            )

    async def _handle_control(self, event: OutputEvent) -> None:
        control = event.payload
        if not isinstance(control, OutputControl) or control.type != OutputControlType.INTERRUPT:
            return

        output_ids = tuple(
            output_id
            for output_id, job in self._jobs.items()
            if self._matches_control(job, control)
        )

        if output_ids:
            await asyncio.gather(
                *(self._cancel_job(output_id, reason=control.reason) for output_id in output_ids),
                return_exceptions=True,
            )

    async def _run_job(
        self,
        *,
        output_id: str,
        lane: OutputLane,
        turn_id: str | None,
        queue: asyncio.Queue[_SpeechSegment],
    ) -> None:
        current_task = asyncio.current_task()
        audio_offset_sec = 0.0

        try:
            while True:
                segment = await queue.get()

                try:
                    if not self._runtime.output.is_active(output_id):
                        break

                    segment_duration_sec = 0.0
                    segment_completed = True

                    if segment.text.strip():
                        async for frame in self._tts.synthesize(segment.text):
                            frame_duration_sec = (
                                frame.samples_per_channel / frame.sample_rate
                                if frame.sample_rate > 0
                                else 0.0
                            )

                            published = await self._runtime.output.publish_audio_frame(
                                frame=frame,
                                lane=lane,
                                output_id=output_id,
                                turn_id=turn_id,
                                metadata={
                                    "source_kind": str(OutputKind.TEXT_CHUNK),
                                    "source_chunk_id": segment.source_chunk_id,
                                    **segment.metadata,
                                },
                            )

                            if published is None:
                                segment_completed = False
                                break

                            segment_duration_sec += frame_duration_sec

                    if segment.source_chunk_id and segment_duration_sec > 0:
                        await self._runtime.output.publish_alignment(
                            text=segment.text,
                            source_chunk_id=segment.source_chunk_id,
                            output_id=output_id,
                            turn_id=turn_id,
                            lane=lane,
                            start_time_sec=audio_offset_sec,
                            end_time_sec=audio_offset_sec + segment_duration_sec,
                            is_final=segment.is_final,
                            partial=not segment_completed,
                            metadata=segment.metadata,
                        )

                    audio_offset_sec += segment_duration_sec

                    if not self._runtime.output.is_active(output_id):
                        break

                    if segment.is_final:
                        await self._runtime.output.complete(
                            lane=lane,
                            output_id=output_id,
                            turn_id=turn_id,
                            metadata={"source_chunk_id": segment.source_chunk_id},
                        )
                        break
                finally:
                    queue.task_done()

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Speech synthesis failed output_id=%s lane=%s", output_id, lane)

            if self._runtime.output.is_active(output_id):
                await self._runtime.output.interrupt(
                    lane=lane,
                    output_id=output_id,
                    reason="speech_synthesis_failed",
                )
        finally:
            job = self._jobs.get(output_id)
            if job is not None and job.task is current_task:
                self._jobs.pop(output_id, None)

    async def _cancel_job(self, output_id: str, *, reason: str) -> None:
        job = self._jobs.pop(output_id, None)
        if job is None:
            return

        if not job.task.done():
            job.task.cancel()

        await asyncio.gather(job.task, return_exceptions=True)
        logger.debug("Speech synthesis job cancelled output_id=%s reason=%s", output_id, reason)

    @staticmethod
    def _matches_control(job: _SpeechJob, control: OutputControl) -> bool:
        if control.target_output_id is not None and job.output_id != control.target_output_id:
            return False
        if control.target_lane is not None and job.lane != control.target_lane:
            return False
        if control.target_turn_id is not None and job.turn_id != control.target_turn_id:
            return False
        return True
