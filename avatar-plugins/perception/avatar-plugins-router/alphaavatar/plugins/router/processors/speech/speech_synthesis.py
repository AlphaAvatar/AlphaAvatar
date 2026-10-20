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
from collections import OrderedDict, deque
from dataclasses import dataclass, field, replace
from math import isfinite

from alphaavatar.agents.avatar.voice import TTSBase, TTSStreamBase
from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvOutput
from alphaavatar.core.env.schemas.metadata import OutputMetadata
from alphaavatar.core.media import AudioFrame
from alphaavatar.core.output.enums import (
    OutputControlType,
    OutputKind,
    OutputLane,
    OutputPlaybackType,
    OutputTextMode,
)
from alphaavatar.core.output.schemas import (
    OutputControl,
    OutputEvent,
    OutputIdentity,
    OutputPlayback,
    OutputSource,
    OutputTextAudioAlignment,
    OutputTextChunk,
)

from .speech_text import SpeechTiming, chunk_end, segment_target, text_weight

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Piece:
    chunk_id: str
    text: str


@dataclass(slots=True)
class _PreparedSpeech:
    text: str
    source_chunk_ids: tuple[str, ...]
    stream: TTSStreamBase | None
    first: AudioFrame | None
    index: int
    final: bool
    first_audio_ms: float
    close_task: asyncio.Task[None] | None = None

    async def aclose(self) -> None:
        if self.stream is not None:
            if self.close_task is None:
                self.close_task = asyncio.create_task(
                    self.stream.aclose(), name="speech_stream_close"
                )
            await wait_for_cleanup(self.close_task)


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
    published_audio_seconds: float = 0.0
    first_audio_seconds: float = 0.8
    budget_rate: float = 14.0
    playback_sequence: int = 0
    playback_ns: int = 0
    playback_checked_ns: int = 0
    played_seconds: float = 0.0
    playback_valid: bool = False
    task: asyncio.Task | None = None
    running: bool = False

    def append(self, chunk: OutputTextChunk) -> None:
        if chunk.text:
            self.pieces.append(_Piece(chunk.chunk_id, chunk.text))
            self.pending_chars += len(chunk.text)
        self.ended = self.ended or chunk.is_final
        self.changed.set()

    def peek(self, limit: int) -> str:
        parts, length = [], 0
        for piece in self.pieces:
            part = piece.text[: limit - length]
            parts.append(part)
            length += len(part)
            if length >= limit:
                break
        return "".join(parts)

    def take(
        self,
        *,
        max_chars: int,
        min_chars: int,
        flush: bool,
        target_chars: int | None = None,
        eager: bool = True,
    ) -> tuple[str, tuple[str, ...]]:
        # Lookahead confirms a decimal/abbreviation without joining the entire answer.
        text = self.peek(max_chars + 64)
        end = chunk_end(
            text,
            minimum=min_chars,
            maximum=max_chars,
            target=target_chars,
            flush=flush or self.ended,
            final=self.ended and len(text) == self.pending_chars,
            eager=eager,
        )
        if not end:
            return "", ()

        remaining, chunks = end, []
        while remaining:
            piece = self.pieces[0]
            used = min(remaining, len(piece.text))
            chunks.append(piece.chunk_id)
            piece.text = piece.text[used:]
            remaining -= used
            if not piece.text:
                self.pieces.popleft()

        self.pending_chars -= end
        return text[:end], tuple(dict.fromkeys(chunks))


class SpeechSynthesisProcessor(RouterProcessorBase):
    """Stream native PCM immediately; playback drives captions, never the reverse."""

    CONSUMER_ID = "router.speech_synthesis"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        tts: TTSBase | None,
        lanes: tuple[OutputLane, ...] = (OutputLane.TRANSIENT, OutputLane.ASSISTANT),
        max_pending_outputs: int = 16,
        max_pending_chars: int = 65_536,
        segment_chars: int = 320,
        min_segment_chars: int = 24,
        flush_interval: float = 0.35,
        delivery_timeout: float = 20.0,
        max_segment_audio_seconds: float = 30.0,
        max_segment_audio_bytes: int = 2_097_152,
    ) -> None:
        super().__init__(runtime=runtime)
        if not 1 <= min_segment_chars <= segment_chars <= min(max_pending_chars, 4096):
            raise ValueError("Invalid synthesis text limits")
        if (
            max_pending_outputs < 1
            or max_segment_audio_bytes < 1
            or not all(
                isfinite(v) and v > 0
                for v in (flush_interval, delivery_timeout, max_segment_audio_seconds)
            )
        ):
            raise ValueError("Synthesis capacities and timeouts must be positive")

        self._tts, self._lanes = tts, lanes
        self._max_outputs, self._max_chars = max_pending_outputs, max_pending_chars
        self._segment_chars, self._min_chars = segment_chars, min_segment_chars
        self._flush_interval, self._timeout = flush_interval, delivery_timeout
        self._audio_seconds, self._audio_bytes = max_segment_audio_seconds, max_segment_audio_bytes
        self._speech_rate = 15.0  # Initial caption estimate only; never a TTS speed setting.
        self._jobs: OrderedDict[str, _SpeechJob] = OrderedDict()
        self._wake = asyncio.Event()
        self._subscription = None
        self._tasks: list[asyncio.Task] = []
        self._close_task: asyncio.Task | None = None
        self._start_task: asyncio.Task | None = None
        self._worker_failures: list[Exception] = []
        self._observed_tasks: set[asyncio.Task] = set()
        self._stopped_tasks: set[asyncio.Task] = set()
        self._externally_cancelled_tasks: set[asyncio.Task] = set()

    @property
    def name(self) -> str:
        return "speech_synthesis"

    @staticmethod
    def _observe_close(task: asyncio.Task) -> None:
        if task.cancelled():
            logger.error("Output consumer cleanup cancelled itself")
        elif (error := task.exception()) is not None:
            logger.error("Output consumer cleanup failed", exc_info=error)

    def _remember_failure(self, error: BaseException, label: str) -> None:
        if isinstance(error, asyncio.CancelledError):
            failure = RuntimeError(f"{label} cancelled itself")
            failure.__cause__ = error
        elif isinstance(error, Exception):
            failure = error
        else:
            raise error
        if all(existing is not failure for existing in self._worker_failures):
            self._worker_failures.append(failure)

    def _observe(self, task: asyncio.Task) -> None:
        if task in self._observed_tasks:
            return
        self._observed_tasks.add(task)
        if task.cancelled():
            if task in self._stopped_tasks or task in self._externally_cancelled_tasks:
                return
            error = asyncio.CancelledError()
        elif (error := task.exception()) is None:
            if task in self._stopped_tasks or task in self._externally_cancelled_tasks:
                return
            error = RuntimeError(f"{self.CONSUMER_ID} worker exited unexpectedly")
        self._remember_failure(error, task.get_name())
        self._ensure_close()

    def _stop_worker(self, task: asyncio.Task) -> None:
        if task.done():
            self._observe(task)
        elif task.cancelling():
            if task not in self._stopped_tasks and task not in self._externally_cancelled_tasks:
                self._externally_cancelled_tasks.add(task)
                self._remember_failure(
                    RuntimeError(f"{task.get_name()} was cancelling before lifecycle shutdown"),
                    task.get_name(),
                )
        else:
            self._stopped_tasks.add(task)
            task.cancel()

    async def _retire_subscription(self) -> None:
        if self._subscription is None:
            return
        if self._worker_failures:
            await self._subscription.fail(self._worker_failures[0])
        else:
            await self._runtime.output.stream.unsubscribe(self.CONSUMER_ID)

    def _cancel(self, job: _SpeechJob) -> None:
        job.cancelled = True
        job.pieces.clear()
        job.pending_chars = 0
        job.changed.set()
        if job.task is not None and job.running and not job.task.cancelling():
            job.task.cancel()
        self._wake.set()

    async def _settle(self, identity: OutputIdentity, reason: str) -> None:
        output, errors = self._runtime.output, []

        async def step(operation, label: str) -> None:
            try:
                await operation
            except asyncio.CancelledError as error:
                failure = RuntimeError(f"{label} cancelled itself")
                failure.__cause__ = error
                errors.append(failure)
            except Exception as error:
                errors.append(error)

        if reason != "synthesis_completed":
            await step(
                output.interrupt(output_id=identity.output_id, reason=reason), "Speech interruption"
            )
        await step(
            output.finish_audio(
                output_id=identity.output_id,
                lane=identity.lane,
                turn_id=identity.scope.turn_id,
                reason=reason,
            ),
            "Speech completion",
        )
        if reason == "synthesis_completed" and not errors:
            await step(
                output.complete(
                    lane=identity.lane, output_id=identity.output_id, turn_id=identity.scope.turn_id
                ),
                "Speech source completion",
            )
        if errors:
            raise ExceptionGroup("Speech settlement failed", errors)

    async def _reject(self, event: OutputEvent, reason: str) -> None:
        value = event.output
        job = self._jobs.get(value.output_id)
        if job is None:
            identity = OutputIdentity(value.output_id, value.lane, value.scope)
            await wait_for_cleanup(
                asyncio.create_task(self._settle(identity, reason), name="speech_rejection")
            )
        else:
            try:
                await self._runtime.output.interrupt(output_id=value.output_id, reason=reason)
            finally:
                self._cancel(job)

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
            if (job := self._jobs.get(event.output.output_id)) is not None:
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
            except Exception as original:
                logger.exception("Speech intake failed output_id=%s", event.output.output_id)
                if not event.output.output_id:
                    raise
                try:
                    await self._reject(event, "invalid_speech_input")
                except BaseException as cleanup:
                    raise original from cleanup

    async def _audio_margin(self, job: _SpeechJob) -> float | None:
        # Optional pacing hint only. A lost/stale timeline entry must make preparation
        # more eager, never prevent speech or create another reliable media subscriber.
        output = self._runtime.output
        now_ns = output.clock.now().monotonic_ns
        entries = ()
        if not job.playback_checked_ns or now_ns - job.playback_checked_ns >= 50_000_000:
            job.playback_checked_ns = now_ns
            entries = await output.timeline.snapshot(
                after_sequence=job.playback_sequence,
                kinds=(OutputKind.PLAYBACK,),
                lanes=(job.identity.lane,),
            )
        for entry in entries:
            value = entry.content
            if (
                entry.session_id != output.session_id
                or value.output_id != job.identity.output_id
                or value.scope != job.identity.scope
                or value.metadata.get("measurement") != "local_audio_queue"
                or not isinstance(value.payload, OutputPlayback)
                or entry.sequence <= job.playback_sequence
            ):
                continue
            job.playback_sequence = entry.sequence
            if entry.monotonic_ns < job.playback_ns:
                continue
            job.playback_ns = entry.monotonic_ns
            job.played_seconds = max(job.played_seconds, value.payload.played_duration_sec)
            job.playback_valid = value.payload.type in (
                OutputPlaybackType.STARTED,
                OutputPlaybackType.PROGRESS,
            )
        if not job.playback_sequence:
            return None
        age = (output.clock.now().monotonic_ns - job.playback_ns) / 1_000_000_000
        if not job.playback_valid or not 0 <= age <= 0.5:
            return 0.0
        # Count only admitted PCM, never an estimated future phrase. Subtract elapsed
        # time even if playback might have stalled: overestimating slack is worse.
        return max(0.0, job.published_audio_seconds - job.played_seconds - age)

    async def _next_segment(self, job: _SpeechJob) -> tuple[str, tuple[str, ...]]:
        clock, started = asyncio.get_running_loop().time, None
        first = job.segments == 0
        # A planning estimate stays below the existing duration/byte safety checks;
        # the actual PCM checks remain authoritative and are never relaxed here.
        audio_limit = self._audio_seconds
        if self._tts is not None:
            audio_limit = min(
                audio_limit,
                self._audio_bytes / (2 * self._tts.sample_rate * self._tts.num_channels),
            )

        while not job.cancelled and self._runtime.output.is_active(job.identity.output_id):
            maximum = min(self._segment_chars, max(1, int(audio_limit * job.budget_rate * 0.8)))
            if first:
                maximum = min(maximum, 112)
            target = segment_target(job.segments, maximum)
            minimum = min(self._min_chars, target)
            job.changed.clear()
            if not job.pending_chars:
                if job.ended:
                    return "", ()
                await job.changed.wait()
                continue

            if started is None:
                started = clock()
            margin = await self._audio_margin(job) if not first else None
            if job.cancelled or not self._runtime.output.is_active(job.identity.output_id):
                raise asyncio.CancelledError
            if first:
                wait = min(self._flush_interval, 0.18)
            elif margin is None:
                wait = min(self._flush_interval, 0.15)
            else:
                wait = min(0.75, max(0.0, margin - job.first_audio_seconds - 0.25))

            now = clock()
            expired = now >= started + wait
            # Later text collects while the CURRENT PCM task continues. An ended source,
            # low audio reserve or a full planning window releases it without extra delay.
            full = text_weight(job.peek(maximum)) >= maximum
            if first or job.ended or expired or full:
                text, chunks = job.take(
                    max_chars=maximum,
                    min_chars=minimum,
                    target_chars=target,
                    flush=expired,
                    eager=first,
                )
                if text:
                    logger.debug(
                        "SPEECH SEGMENT output_id=%s segment=%d target_units=%d "
                        "max_units=%d units=%d chars=%d pending_chars=%d "
                        "source_ended=%s collect_ms=%.1f audio_margin_ms=%s",
                        job.identity.output_id,
                        job.segments + 1,
                        target,
                        maximum,
                        text_weight(text),
                        len(text),
                        job.pending_chars,
                        job.ended,
                        (clock() - started) * 1000,
                        round(margin * 1000, 1) if margin is not None else None,
                    )
                    return text, chunks
            if expired:
                # No safe prefix yet (e.g. "$213."). A timer cannot resolve that
                # ambiguity. Wait for actual lookahead/finality, not a busy polling loop.
                await job.changed.wait()
            else:
                try:
                    async with asyncio.timeout(min(0.05, max(0.0, started + wait - clock()))):
                        await job.changed.wait()
                except TimeoutError:
                    pass
        raise asyncio.CancelledError

    async def _prepare(self, job: _SpeechJob) -> _PreparedSpeech | None:
        text, chunks = await self._next_segment(job)
        if not text:
            return None

        stream, first = None, None
        started = asyncio.get_running_loop().time()
        try:
            if not text.isspace():
                assert self._tts is not None
                stream = self._tts.synthesize(text)
                # Voice owns request/read deadlines and pre-audio retries. Do not replace a
                # provider failure with a second, unrelated Router timeout.
                logger.debug(
                    "SPEECH REQUEST output_id=%s segment=%d tts_request_id=%s chars=%d",
                    job.identity.output_id,
                    job.segments + 1,
                    stream.request_id,
                    len(text),
                )
                try:
                    first = await anext(stream)
                except StopAsyncIteration:
                    raise RuntimeError("TTS returned no audio for nonempty text") from None
                self._validate_frame(first)
            if job.cancelled or not self._runtime.output.is_active(job.identity.output_id):
                raise asyncio.CancelledError
        except BaseException as original:
            if stream is not None:
                try:
                    await wait_for_cleanup(asyncio.create_task(stream.aclose()))
                except BaseException as cleanup:
                    raise original from cleanup
            raise

        elapsed = asyncio.get_running_loop().time() - started
        if stream is not None:
            job.first_audio_seconds = min(2.5, max(0.2, elapsed, job.first_audio_seconds * 0.75))
        job.segments += 1
        return _PreparedSpeech(
            text,
            chunks,
            stream,
            first,
            job.segments,
            job.ended and job.pending_chars == 0,
            elapsed * 1000,
        )

    def _validate_frame(self, frame: AudioFrame) -> None:
        if not isinstance(frame, AudioFrame) or (frame.sample_rate, frame.num_channels) != (
            self._tts.sample_rate,
            self._tts.num_channels,
        ):
            raise ValueError("TTS audio format changed")
        if not 0 < frame.samples_per_channel <= frame.sample_rate:
            raise ValueError("Invalid TTS audio frame duration")

    async def _run_job(self, job: _SpeechJob) -> None:
        job.running = True
        identity, output, offset = job.identity, self._runtime.output, 0.0
        reason, stage = "synthesis_completed", "prepare"
        preparing: asyncio.Task[_PreparedSpeech | None] | None = None
        current: _PreparedSpeech | None = None
        alignments: asyncio.Queue[OutputTextAudioAlignment | None] = asyncio.Queue(maxsize=8)

        async def publish_alignments() -> None:
            while (alignment := await alignments.get()) is not None:
                async with asyncio.timeout(self._timeout):
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
                    raise RuntimeError("Speech alignment was not admitted")

        publisher = asyncio.create_task(publish_alignments(), name="speech_alignments")

        def check_publisher() -> None:
            if publisher.done():
                if publisher.cancelled():
                    raise RuntimeError("Speech alignment writer cancelled itself")
                publisher.result()
                raise RuntimeError("Speech alignment writer stopped unexpectedly")

        def align(
            segment: _PreparedSpeech, duration: float, *, final: bool, partial: bool = False
        ) -> None:
            check_publisher()
            alignments.put_nowait(
                OutputTextAudioAlignment(
                    text=segment.text,
                    alignment_id=f"{identity.output_id}:speech:{segment.index}",
                    source_chunk_ids=segment.source_chunk_ids,
                    start_time_sec=offset,
                    end_time_sec=offset + duration,
                    is_final=segment.final,
                    partial=partial,
                    timing_source="text_boundary"
                    if segment.stream is None
                    else "measured_audio"
                    if final
                    else "estimated_speech_rate",
                    revision=int(final and segment.stream is not None),
                    duration_final=final,
                )
            )

        try:
            preparing = asyncio.create_task(self._prepare(job), name="speech_prepare")
            while True:
                stage = "prepare"
                try:
                    current = await asyncio.shield(preparing)
                except asyncio.CancelledError as error:
                    if preparing.cancelled():
                        preparing = None
                    if not asyncio.current_task().cancelling() and not job.cancelled:
                        raise RuntimeError("TTS preparation cancelled itself") from error
                    raise
                except Exception:
                    preparing = None  # A failed prepare has already closed its acquired stream.
                    raise

                preparing = None  # The returned stream is now explicitly owned by current.
                if current is None:
                    break
                if job.cancelled or not output.is_active(identity.output_id):
                    raise asyncio.CancelledError
                if not current.final:
                    preparing = asyncio.create_task(self._prepare(job), name="speech_prepare")

                timing = SpeechTiming.create(current.text)
                estimate = timing.cumulative[-1] / self._speech_rate if current.stream else 0.0
                align(current, estimate, final=current.stream is None)
                samples = size = frames = 0
                complete = False
                try:
                    if current.stream is not None:
                        frame = current.first
                        while frame is not None:
                            if job.cancelled or not output.is_active(identity.output_id):
                                raise asyncio.CancelledError

                            check_publisher()
                            self._validate_frame(frame)
                            size += len(frame.data)
                            frames += 1
                            if (
                                samples + frame.samples_per_channel
                                > self._audio_seconds * frame.sample_rate
                                or size > self._audio_bytes
                                or frames > 4096
                            ):
                                raise RuntimeError("Speech segment exceeds its audio limit")

                            # No alignment, subtitle network or typing timer is awaited here.
                            stage = "audio_delivery"
                            async with asyncio.timeout(self._timeout):
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

                            samples += frame.samples_per_channel
                            job.published_audio_seconds += frame.duration_sec
                            if frames == 1:
                                current.first = None
                                logger.debug(
                                    "Speech first audio output_id=%s segment=%d "
                                    "chars=%d first_audio_ms=%.1f",
                                    identity.output_id,
                                    current.index,
                                    len(current.text),
                                    current.first_audio_ms,
                                )
                            stage = "audio_read"
                            frame = await anext(current.stream, None)
                    complete = True
                finally:
                    duration = samples / self._tts.sample_rate if samples else 0.0
                    if current.stream is not None:
                        # Correct timing in place; a failed prefix never implies a complete phrase.
                        align(current, duration, final=True, partial=not complete)

                await current.aclose()
                if duration and complete:
                    # Per-output estimate: transient status cannot change an answer's budget.
                    job.budget_rate = min(60.0, max(1.0, text_weight(current.text) / duration))
                    rate = timing.cumulative[-1] / duration
                    self._speech_rate = min(30.0, max(6.0, 0.5 * self._speech_rate + 0.5 * rate))
                    logger.debug(
                        "Speech audio complete output_id=%s segment=%d "
                        "samples=%d audio_seconds=%.3f",
                        identity.output_id,
                        current.index,
                        samples,
                        duration,
                    )
                offset += duration
                last = current.final
                current = None
                if last:
                    break
        except asyncio.CancelledError:
            reason = "synthesis_interrupted"
            raise
        except Exception:
            reason = "speech_synthesis_failed"
            logger.exception(
                "Speech synthesis failed output_id=%s stage=%s", identity.output_id, stage
            )
        finally:

            async def settle() -> None:
                errors: list[Exception] = []
                abandoned = current
                if preparing is not None:
                    if not preparing.done():
                        preparing.cancel()
                    (result,) = await asyncio.gather(preparing, return_exceptions=True)
                    if isinstance(result, _PreparedSpeech):
                        try:
                            await result.aclose()
                        except Exception as error:
                            errors.append(error)
                    elif isinstance(result, Exception):
                        errors.append(result)
                if abandoned is not None:
                    try:
                        await abandoned.aclose()
                    except Exception as error:
                        errors.append(error)
                try:
                    # Only source settlement waits for timing publication; PCM never does.
                    async with asyncio.timeout(self._timeout):
                        if not publisher.done():
                            await alignments.put(None)
                        await asyncio.shield(publisher)
                except BaseException as error:
                    if not publisher.done():
                        publisher.cancel()
                    await asyncio.gather(publisher, return_exceptions=True)
                    if isinstance(error, Exception):
                        errors.append(error)
                    elif isinstance(error, asyncio.CancelledError):
                        failure = RuntimeError("Speech alignment settlement cancelled itself")
                        failure.__cause__ = error
                        errors.append(failure)
                    else:
                        raise
                try:
                    await self._settle(identity, "speech_synthesis_failed" if errors else reason)
                except Exception as error:
                    errors.append(error)
                if errors:
                    raise ExceptionGroup("Speech streaming cleanup failed", errors)

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
            (result,) = await asyncio.gather(self._start_task, return_exceptions=True)
            if isinstance(result, Exception):
                self._remember_failure(result, "Speech startup")

        workers, jobs = tuple(self._tasks), tuple(self._jobs.values())
        for task in workers:
            self._stop_worker(task)
        for job in jobs:
            self._cancel(job)
        try:
            await self._retire_subscription()
        except BaseException as error:
            self._remember_failure(error, "Speech subscription retirement")

        tasks = tuple(dict.fromkeys((*workers, *(j.task for j in jobs if j.task is not None))))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for task in workers:
            self._observe(task)
        for task, result in zip(tasks, results, strict=True):
            if task not in workers and isinstance(result, Exception):
                self._remember_failure(result, "Speech job")

        try:
            results = await asyncio.gather(
                *(
                    self._settle(job.identity, "speech_synthesis_stopping")
                    for job in jobs
                    if job.task is None
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    self._remember_failure(result, "Unstarted speech settlement")
        finally:
            self._jobs.clear()
            self._tasks.clear()
            self._subscription = None
        if self._worker_failures:
            raise ExceptionGroup("Speech synthesis cleanup failed", self._worker_failures)

    def _ensure_close(self) -> asyncio.Task:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name=f"{self.CONSUMER_ID}:close")
            self._close_task.add_done_callback(self._observe_close)
        return self._close_task

    async def stop(self) -> None:
        await wait_for_cleanup(self._ensure_close())
