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
from dataclasses import dataclass, field, replace
from math import isfinite

from alphaavatar.agents.avatar.voice import TTSBase
from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvOutput
from alphaavatar.core.env.schemas.metadata import OutputMetadata
from alphaavatar.core.output.enums import OutputControlType, OutputKind, OutputLane, OutputTextMode
from alphaavatar.core.output.schemas import (
    OutputControl,
    OutputEvent,
    OutputIdentity,
    OutputSource,
    OutputTextAudioAlignment,
    OutputTextChunk,
)

logger = logging.getLogger(__name__)
_BOUNDARY = re.compile(r"[.!?。！？；;\n](?:[\"'”’）)]|\s)*")


@dataclass(slots=True)
class _Piece:
    chunk_id: str
    text: str


@dataclass(slots=True)
class _SpeechJob:
    identity: OutputIdentity
    source: OutputSource
    metadata: OutputMetadata
    pieces: deque[_Piece] = field(default_factory=deque)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    pending_chars: int = 0
    ended: bool = False
    cancelled: bool = False
    segments: int = 0
    task: asyncio.Task | None = None
    running: bool = False

    def append(self, chunk: OutputTextChunk) -> None:
        self.pieces.append(_Piece(chunk.chunk_id, chunk.text))
        self.pending_chars += len(chunk.text)
        self.ended = self.ended or chunk.is_final
        self.changed.set()

    def take(self, *, max_chars: int, min_chars: int, flush: bool) -> tuple[str, tuple[str, ...]]:
        parts, length = [], 0
        for piece in self.pieces:
            parts.append(piece.text[: max_chars - length])
            length += len(parts[-1])
            if length >= max_chars:
                break
        text = "".join(parts)
        if not text:
            return "", ()
        matches = [match.end() for match in _BOUNDARY.finditer(text) if match.end() >= min_chars]
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
    """Bounded phrase synthesis with independent intake, interruption and transport playout."""

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
            isfinite(value) and value > 0 for value in (flush_interval, synthesis_timeout)
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
    def _observe(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("Speech task failed", exc_info=task.exception())

    def _cancel(self, job: _SpeechJob) -> None:
        job.cancelled = True
        job.pieces.clear()
        job.pending_chars = 0
        job.changed.set()
        if job.task is not None and job.running and not job.task.cancelling():
            job.task.cancel()
        self._wake.set()

    async def _reject(self, event: OutputEvent, reason: str) -> None:
        output = event.output
        await self._runtime.output.interrupt(output_id=output.output_id, reason=reason)
        if output.output_id not in self._jobs:
            await self._runtime.output.finish_audio(
                output_id=output.output_id,
                lane=output.lane,
                turn_id=output.scope.turn_id,
                reason=reason,
            )
        else:
            self._cancel(self._jobs[output.output_id])

    async def _handle_text(self, event: OutputEvent) -> None:
        output, chunk = event.output, event.output.payload
        if not isinstance(chunk, OutputTextChunk) or chunk.mode != OutputTextMode.AUDIO_SYNCED:
            return
        if not self._runtime.output.is_active(output.output_id):
            return
        for previous in self._jobs.values():
            if not self._runtime.output.is_active(previous.identity.output_id):
                self._cancel(previous)
        if self._tts is None:
            await self._reject(event, "tts_unavailable")
            return

        job = self._jobs.get(output.output_id)
        identity = OutputIdentity(output.output_id, output.lane, output.scope)
        if job is None:
            if len(self._jobs) >= self._max_outputs:
                await self._reject(event, "speech_output_capacity")
                return
            job = _SpeechJob(
                identity,
                replace(output.source, producer="router.speech_synthesis"),
                output.metadata,
            )
            self._jobs[output.output_id] = job
        if job.identity != identity:
            raise ValueError("Speech output identity changed")
        if job.ended:
            raise ValueError("Source text followed its completion")
        if (
            sum(item.pending_chars for item in self._jobs.values()) + len(chunk.text)
            > self._max_chars
        ):
            await self._reject(event, "speech_text_capacity")
            return

        job.append(chunk)
        self._wake.set()

    async def _handle_control(self, event: OutputEvent) -> None:
        control = event.output.payload
        if not isinstance(control, OutputControl):
            return

        if control.type == OutputControlType.INTERRUPT:
            for identity in control.targets:
                job = self._jobs.get(identity.output_id)
                if job is not None:
                    if job.identity != identity:
                        raise ValueError("Interrupt identity changed")
                    self._cancel(job)
                elif (
                    identity.lane in self._lanes
                    and self._runtime.output.text_mode(identity.output_id)
                    == OutputTextMode.AUDIO_SYNCED
                ):
                    await self._runtime.output.finish_audio(
                        output_id=identity.output_id,
                        lane=identity.lane,
                        turn_id=identity.scope.turn_id,
                        reason=control.reason,
                    )
        elif control.type == OutputControlType.TEXT_COMPLETE:
            job = self._jobs.get(event.output.output_id)
            if job is not None:
                job.ended = True
                job.changed.set()

    async def _intake(self) -> None:
        while True:
            event = await self._subscription.get()
            try:
                if event.output.kind == OutputKind.TEXT_CHUNK:
                    await self._handle_text(event)
                elif event.output.kind == OutputKind.CONTROL:
                    await self._handle_control(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Speech intake failed output_id=%s", event.output.output_id)
                if event.output.output_id:
                    await self._reject(event, "invalid_speech_input")

    async def _next_segment(self, job: _SpeechJob) -> tuple[str, tuple[str, ...]]:
        deadline = None
        while not job.cancelled and self._runtime.output.is_active(job.identity.output_id):
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
                pass
        raise asyncio.CancelledError

    async def _run_job(self, job: _SpeechJob) -> None:
        job.running = True
        identity, output, offset, reason = (
            job.identity,
            self._runtime.output,
            0.0,
            "synthesis_completed",
        )
        try:
            while not job.cancelled and output.is_active(identity.output_id):
                text, chunks = await self._next_segment(job)
                if not text and job.ended:
                    break

                duration = 0.0
                if not text.isspace():
                    async with asyncio.timeout(self._timeout):
                        async with aclosing(self._tts.synthesize(text)) as frames:
                            async for frame in frames:
                                event = await output.publish(
                                    EnvOutput(
                                        kind=OutputKind.AUDIO_FRAME,
                                        output_id=identity.output_id,
                                        lane=identity.lane,
                                        scope=identity.scope,
                                        source=job.source,
                                        payload=frame,
                                        metadata=job.metadata,
                                    )
                                )
                                if event is None:
                                    raise asyncio.CancelledError
                                duration += frame.samples_per_channel / frame.sample_rate
                    if duration <= 0:
                        raise RuntimeError("TTS returned no audio for nonempty text")
                job.segments += 1
                # Whitespace is a text boundary, not synthesized/estimated audible speech.
                alignment = OutputTextAudioAlignment(
                    text=text,
                    alignment_id=f"{identity.output_id}:phrase:{job.segments}",
                    source_chunk_ids=chunks,
                    start_time_sec=offset,
                    end_time_sec=offset + duration,
                    is_final=job.ended and job.pending_chars == 0,
                    timing_source="text_boundary" if text.isspace() else "estimated_phrase",
                )
                event = await output.publish(
                    EnvOutput(
                        kind=OutputKind.ALIGNMENT,
                        output_id=identity.output_id,
                        lane=identity.lane,
                        scope=identity.scope,
                        source=job.source,
                        payload=alignment,
                        metadata=job.metadata,
                    )
                )
                if event is None:
                    raise asyncio.CancelledError
                offset += duration
            if job.cancelled or not output.is_active(identity.output_id):
                reason = "synthesis_interrupted"
        except asyncio.CancelledError:
            reason = "synthesis_interrupted"
            raise
        except Exception:
            reason = "speech_synthesis_failed"
            logger.exception("Speech synthesis failed output_id=%s", identity.output_id)
        finally:

            async def settle() -> None:
                if reason != "synthesis_completed":
                    await output.interrupt(output_id=identity.output_id, reason=reason)
                await output.finish_audio(
                    output_id=identity.output_id,
                    lane=identity.lane,
                    turn_id=identity.scope.turn_id,
                    reason=reason,
                )
                if reason == "synthesis_completed":
                    await output.complete(
                        lane=identity.lane,
                        output_id=identity.output_id,
                        turn_id=identity.scope.turn_id,
                    )

            await wait_for_cleanup(asyncio.create_task(settle(), name="speech_settlement"))

    async def _synthesize(self) -> None:
        while True:
            self._wake.clear()
            if not self._jobs:
                await self._wake.wait()
                continue
            job = next(iter(self._jobs.values()))
            job.task = asyncio.create_task(self._run_job(job), name=f"tts:{job.identity.output_id}")
            try:
                await asyncio.shield(job.task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            finally:
                if job.task.done():
                    self._jobs.pop(job.identity.output_id, None)

    async def _start(self) -> None:
        self._subscription = await self._runtime.output.stream.subscribe(
            self.CONSUMER_ID,
            kinds=(OutputKind.TEXT_CHUNK, OutputKind.CONTROL),
            control_types=(OutputControlType.INTERRUPT, OutputControlType.TEXT_COMPLETE),
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

        if self._subscription is not None:
            await self._runtime.output.stream.unsubscribe(self.CONSUMER_ID)
            self._subscription = None

        tasks = tuple(
            dict.fromkeys((*self._tasks, *(job.task for job in jobs if job.task is not None)))
        )
        results = list(await asyncio.gather(*tasks, return_exceptions=True))

        async def settle(job: _SpeechJob) -> None:
            identity, failures = job.identity, []
            # Keep interrupt -> synthesis barrier ordering; one failure must not skip the other.
            try:
                await self._runtime.output.interrupt(
                    output_id=identity.output_id, reason="speech_synthesis_stopping"
                )
            except asyncio.CancelledError as exc:
                error = RuntimeError("Speech interruption cancelled itself")
                error.__cause__ = exc
                failures.append(error)
            except Exception as exc:
                failures.append(exc)
            try:
                await self._runtime.output.finish_audio(
                    output_id=identity.output_id,
                    lane=identity.lane,
                    turn_id=identity.scope.turn_id,
                    reason="speech_synthesis_stopping",
                )
            except asyncio.CancelledError as exc:
                error = RuntimeError("Speech completion cancelled itself")
                error.__cause__ = exc
                failures.append(error)
            except Exception as exc:
                failures.append(exc)
            if failures:
                raise ExceptionGroup("Unstarted speech settlement failed", failures)

        settlements = tuple(settle(job) for job in jobs if job.task is None)
        try:
            results.extend(await asyncio.gather(*settlements, return_exceptions=True))
        finally:
            self._jobs.clear()
            self._tasks.clear()

        # Worker cancellations above are deliberate; accepted terminal failures are not.
        errors = list(
            {id(result): result for result in results if isinstance(result, Exception)}.values()
        )
        for result in results[len(tasks) :]:
            if isinstance(result, asyncio.CancelledError):
                error = RuntimeError("Speech settlement cancelled itself")
                error.__cause__ = result
                errors.append(error)
        if errors:
            raise ExceptionGroup("Speech synthesis cleanup failed", errors)

    async def stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="speech_close")
        await wait_for_cleanup(self._close_task)
