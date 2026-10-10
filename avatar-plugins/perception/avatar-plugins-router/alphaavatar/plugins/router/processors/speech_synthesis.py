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
import re
from collections import OrderedDict, deque
from contextlib import aclosing
from dataclasses import dataclass, field
from math import isfinite

from alphaavatar.agents.avatar.voice import TTSBase
from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.output.enums import OutputControlType, OutputKind, OutputLane, OutputTextMode
from alphaavatar.core.output.schemas import OutputControl, OutputEvent, OutputTextChunk

logger = logging.getLogger(__name__)
_BOUNDARY = re.compile(r"[.!?。！？；;\n](?:[\"'”’）)]|\s)*")


@dataclass(slots=True)
class _Piece:
    chunk_id: str
    text: str


@dataclass(slots=True)
class _SpeechJob:
    output_id: str
    lane: OutputLane
    turn_id: str | None
    metadata: dict
    pieces: deque[_Piece] = field(default_factory=deque)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    pending_chars: int = 0
    ended: bool = False
    cancelled: bool = False
    segments: int = 0
    task: asyncio.Task | None = None

    def append(self, chunk: OutputTextChunk) -> None:
        self.pieces.append(_Piece(chunk.chunk_id, chunk.text))
        self.pending_chars += len(chunk.text)
        self.ended = self.ended or chunk.is_final
        self.changed.set()

    def take(self, *, max_chars: int, min_chars: int, flush: bool) -> tuple[str, tuple[str, ...]]:
        # Inspect a bounded prefix. Do not concatenate an entire long answer for each token.
        parts, length = [], 0
        for piece in self.pieces:
            parts.append(piece.text[: max_chars - length])
            length += len(parts[-1])
            if length >= max_chars:
                break
        text = "".join(parts)
        if not text:
            return "", ()
        matches = [m.end() for m in _BOUNDARY.finditer(text) if m.end() >= min_chars]
        if matches:
            end = matches[0]
        elif self.pending_chars >= max_chars:
            boundary = text.rfind(" ", min_chars)
            end = boundary + 1 if boundary >= min_chars else len(text)
        elif flush or self.ended:
            end = len(text)
        else:
            return "", ()
        remaining, chunks = end, []
        while remaining:
            piece = self.pieces[0]
            used = min(remaining, len(piece.text))
            if used == 0:
                self.pieces.popleft()
                continue
            chunks.append(piece.chunk_id)
            piece.text = piece.text[used:]
            remaining -= used
            if not piece.text:
                self.pieces.popleft()
        self.pending_chars -= end
        return text[:end], tuple(dict.fromkeys(chunks))


class SpeechSynthesisProcessor(RouterProcessorBase):
    """Bounded phrase synthesis; model tokens never become individual TTS requests.

    Intake and interruption are independent of synthesis. A single producer keeps
    commentary and answer audio ordered; RTC owns actual playout and its receipts.
    """

    CONSUMER_ID = "router.speech_synthesis"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        tts: TTSBase | None,
        lanes: tuple[OutputLane, ...] = (OutputLane.TRANSIENT, OutputLane.ASSISTANT),
        max_pending_outputs: int = 16,
        max_pending_chars: int = 65_536,
        segment_chars: int = 240,
        min_segment_chars: int = 24,
        flush_interval: float = 0.35,
        synthesis_timeout: float = 20.0,
    ) -> None:
        super().__init__(runtime=runtime)
        if not 1 <= min_segment_chars <= segment_chars <= max_pending_chars:
            raise ValueError("Invalid synthesis text limits")
        if max_pending_outputs < 1 or not all(
            isfinite(t) and t > 0 for t in (flush_interval, synthesis_timeout)
        ):
            raise ValueError("Synthesis capacities and timeouts must be positive")
        self._tts, self._lanes = tts, lanes
        self._max_outputs, self._max_chars = max_pending_outputs, max_pending_chars
        self._segment_chars, self._min_chars = segment_chars, min_segment_chars
        self._flush_interval, self._timeout = flush_interval, synthesis_timeout
        self._jobs: OrderedDict[str, _SpeechJob] = OrderedDict()
        self._wake = asyncio.Event()
        self._subscription = None
        self._tasks: list[asyncio.Task] = []
        self._close_task: asyncio.Task | None = None
        self._start_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return "speech_synthesis"

    @staticmethod
    def _matches(job: _SpeechJob, control: OutputControl) -> bool:
        return (
            (control.target_output_id is None or job.output_id == control.target_output_id)
            and (control.target_lane is None or job.lane == control.target_lane)
            and (control.target_turn_id is None or job.turn_id == control.target_turn_id)
        )

    @staticmethod
    def _observe(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("Speech task failed", exc_info=task.exception())

    def _cancel(self, job: _SpeechJob) -> None:
        job.cancelled = True
        job.pieces.clear()
        job.pending_chars = 0
        job.changed.set()
        if job.task is not None:
            job.task.cancel()
        self._wake.set()

    async def _reject(self, event: OutputEvent, reason: str) -> None:
        await self._runtime.output.interrupt(output_id=event.output_id, reason=reason)
        if event.output_id not in self._jobs:
            await self._runtime.output.finish_audio(
                output_id=event.output_id, lane=event.lane, turn_id=event.turn_id, reason=reason
            )
        else:
            self._cancel(self._jobs[event.output_id])

    async def _handle_text(self, event: OutputEvent) -> None:
        chunk = event.payload
        if not isinstance(chunk, OutputTextChunk) or chunk.mode != OutputTextMode.AUDIO_SYNCED:
            return
        if not event.output_id or not self._runtime.output.is_active(event.output_id):
            return
        for previous in self._jobs.values():
            if not self._runtime.output.is_active(previous.output_id):
                self._cancel(previous)
        if self._tts is None:
            await self._reject(event, "tts_unavailable")
            return
        job = self._jobs.get(event.output_id)
        if job is None:
            if len(self._jobs) >= self._max_outputs:
                await self._reject(event, "speech_output_capacity")
                return
            job = _SpeechJob(event.output_id, event.lane, event.turn_id, dict(event.metadata))
            self._jobs[event.output_id] = job
        if job.lane != event.lane or job.turn_id != event.turn_id:
            raise ValueError("Speech output identity changed")
        if job.ended:
            raise ValueError("Source text followed its completion")
        pending = sum(item.pending_chars for item in self._jobs.values())
        if pending + len(chunk.text) > self._max_chars:
            await self._reject(event, "speech_text_capacity")
            return
        job.append(chunk)
        self._wake.set()

    async def _handle_control(self, event: OutputEvent) -> None:
        control = event.payload
        if not isinstance(control, OutputControl):
            return
        jobs = tuple(job for job in self._jobs.values() if self._matches(job, control))
        if control.type == OutputControlType.INTERRUPT:
            for job in jobs:
                self._cancel(job)
            for output_id in event.metadata.get("interrupted_output_ids", ()):
                output = self._runtime.output
                if (
                    output_id in self._jobs
                    or output.text_mode(output_id) != OutputTextMode.AUDIO_SYNCED
                ):
                    continue
                identity = output.output_identity(output_id)
                if identity is not None and identity[0] in self._lanes:
                    lane, turn_id = identity
                    await output.finish_audio(
                        output_id=output_id, lane=lane, turn_id=turn_id, reason=control.reason
                    )
        elif control.type == OutputControlType.TEXT_COMPLETE:
            for job in jobs:
                job.ended = True
                job.changed.set()

    async def _intake(self) -> None:
        while True:
            event = await self._subscription.get()
            try:
                if event.kind == OutputKind.TEXT_CHUNK:
                    await self._handle_text(event)
                elif event.kind == OutputKind.CONTROL:
                    await self._handle_control(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Speech intake failed output_id=%s", event.output_id)
                if event.output_id:
                    await self._reject(event, "invalid_speech_input")

    async def _next_segment(self, job: _SpeechJob) -> tuple[str, tuple[str, ...]]:
        deadline = None
        while not job.cancelled and self._runtime.output.is_active(job.output_id):
            job.changed.clear()
            now = asyncio.get_running_loop().time()
            if job.pending_chars and deadline is None:
                deadline = now + self._flush_interval
            text, chunks = job.take(
                max_chars=self._segment_chars,
                min_chars=self._min_chars,
                flush=deadline is not None and now >= deadline,
            )
            if text or job.ended:
                return text, chunks
            try:
                timeout = self._flush_interval if deadline is None else max(0, deadline - now)
                await asyncio.wait_for(job.changed.wait(), timeout=timeout)
            except TimeoutError:
                pass  # The original deadline does not slide with every arriving token.
        raise asyncio.CancelledError

    async def _run_job(self, job: _SpeechJob) -> None:
        output, offset, reason = self._runtime.output, 0.0, "synthesis_completed"
        try:
            while not job.cancelled and output.is_active(job.output_id):
                text, chunks = await self._next_segment(job)
                if not text and job.ended:
                    break
                if not text.strip():
                    continue

                duration = 0.0
                async with asyncio.timeout(self._timeout):
                    async with aclosing(self._tts.synthesize(text)) as frames:
                        async for frame in frames:
                            event = await output.publish_audio_frame(
                                frame=frame,
                                lane=job.lane,
                                output_id=job.output_id,
                                turn_id=job.turn_id,
                                metadata=job.metadata,
                            )
                            if event is None:
                                raise asyncio.CancelledError

                            duration += frame.samples_per_channel / frame.sample_rate

                if duration <= 0:
                    raise RuntimeError("TTS returned no audio for nonempty text")

                # Only a fully synthesized phrase receives an alignment. No invented partial text.
                job.segments += 1
                await output.publish_alignment(
                    text=text,
                    source_chunk_id=chunks[0],
                    source_chunk_ids=chunks,
                    alignment_id=f"{job.output_id}:phrase:{job.segments}",
                    output_id=job.output_id,
                    turn_id=job.turn_id,
                    lane=job.lane,
                    start_time_sec=offset,
                    end_time_sec=offset + duration,
                    is_final=job.ended and job.pending_chars == 0,
                    timing_source="estimated_phrase",
                    metadata=job.metadata,
                )
                offset += duration
            if job.cancelled or not output.is_active(job.output_id):
                reason = "synthesis_interrupted"
        except asyncio.CancelledError:
            reason = "synthesis_interrupted"
            raise
        except Exception:
            reason = "speech_synthesis_failed"
            logger.exception("Speech synthesis failed output_id=%s", job.output_id)
        finally:

            async def settle() -> None:
                if reason != "synthesis_completed":
                    await output.interrupt(output_id=job.output_id, reason=reason)
                await output.finish_audio(
                    output_id=job.output_id, lane=job.lane, turn_id=job.turn_id, reason=reason
                )
                if reason == "synthesis_completed":
                    await output.complete(
                        lane=job.lane, output_id=job.output_id, turn_id=job.turn_id
                    )

            await wait_for_cleanup(asyncio.create_task(settle(), name="speech_settlement"))

    async def _synthesize(self) -> None:
        while True:
            self._wake.clear()
            if not self._jobs:
                await self._wake.wait()
                continue
            job = next(iter(self._jobs.values()))
            job.task = asyncio.create_task(self._run_job(job), name=f"tts:{job.output_id}")
            try:
                await asyncio.shield(job.task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            finally:
                if job.task.done():
                    self._jobs.pop(job.output_id, None)

    async def _start(self) -> None:
        self._subscription = await self._runtime.output.stream.subscribe(
            self.CONSUMER_ID,
            kinds=(OutputKind.TEXT_CHUNK, OutputKind.CONTROL),
            lanes=self._lanes,
            max_pending=128,
            reliable=True,
        )
        for name, operation in (
            ("speech_intake", self._intake()),
            ("speech_synthesis", self._synthesize()),
        ):
            task = asyncio.create_task(operation, name=name)
            task.add_done_callback(self._observe)
            self._tasks.append(task)

    async def start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Output consumer is closing or closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="output_consumer_start")
        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None:
                raise RuntimeError("Output consumer closed during startup")
        except BaseException as original:
            try:
                await self.stop()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def _close(self) -> None:
        if self._start_task is not None:
            if not self._start_task.done():
                self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)

        for task in self._tasks:
            task.cancel()

        jobs = tuple(self._jobs.values())
        for job in jobs:
            self._cancel(job)

        # Release reliable intake before awaiting terminal publications during cleanup.
        if self._subscription is not None:
            await self._runtime.output.stream.unsubscribe(self.CONSUMER_ID)
            self._subscription = None
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for job in jobs:
            if job.task is not None:
                await asyncio.gather(job.task, return_exceptions=True)
            else:
                await self._runtime.output.interrupt(
                    output_id=job.output_id, reason="speech_synthesis_stopping"
                )
                await self._runtime.output.finish_audio(
                    output_id=job.output_id,
                    lane=job.lane,
                    turn_id=job.turn_id,
                    reason="speech_synthesis_stopping",
                )
        self._jobs.clear()
        self._tasks.clear()

    async def stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="speech_close")
        await wait_for_cleanup(self._close_task)
