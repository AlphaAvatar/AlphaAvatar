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
from typing import TYPE_CHECKING

from alphaavatar.agents.avatar.voice import TTSBase
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvOutput
from alphaavatar.core.output.enums import OutputKind
from alphaavatar.core.output.enums.message_phase import OutputMessagePhase
from alphaavatar.core.output.schemas import OutputIdentity, OutputTextAudioAlignment

from ..speech_text import SpeechTiming, text_weight
from .handoff import AnswerHandoff
from .segmentation import SegmentPreparer
from .state import PreparedSpeech, SpeechJob, SpeechLimits

if TYPE_CHECKING:
    from alphaavatar.core.output.runtime import OutputRuntime

logger = logging.getLogger(__name__)


class SpeechStreamer:
    """Own one job's PCM, bounded alignment writer and terminal settlement."""

    def __init__(
        self,
        *,
        output: OutputRuntime,
        tts: TTSBase | None,
        segments: SegmentPreparer,
        handoff: AnswerHandoff,
        capacity: int,
        limits: SpeechLimits,
    ) -> None:
        self._output, self._tts, self._segments = output, tts, segments
        self._handoff, self._capacity, self._limits = handoff, capacity, limits
        self._speech_rate = 15.0  # Caption estimate only, not a TTS speed setting.

    async def settle(self, identity: OutputIdentity, reason: str) -> None:
        output, errors = self._output, []

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

    async def run(self, job: SpeechJob) -> None:
        job.running = True
        identity, output, offset = job.identity, self._output, 0.0
        reason, stage = "synthesis_completed", "prepare"
        preparing: asyncio.Task[PreparedSpeech | None] | None = None
        current: PreparedSpeech | None = None
        alignments: asyncio.Queue[OutputTextAudioAlignment | None] = asyncio.Queue(maxsize=8)

        async def publish_alignments() -> None:
            while (alignment := await alignments.get()) is not None:
                async with asyncio.timeout(self._limits.timeout):
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
                if event is None and not job.cancelled and output.is_active(identity.output_id):
                    raise RuntimeError("Speech alignment was not admitted")

        publisher = asyncio.create_task(publish_alignments(), name="speech_alignments")

        def check_publisher() -> None:
            if publisher.done():
                if publisher.cancelled():
                    raise RuntimeError("Speech alignment writer cancelled itself")
                publisher.result()
                raise RuntimeError("Speech alignment writer stopped unexpectedly")

        def align(
            segment: PreparedSpeech, duration: float, *, final: bool, partial: bool = False
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
            preparing = asyncio.create_task(self._handoff.first_segment(job), name="speech_prepare")
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
                    if job.handoff is not None and job.handoff.done():
                        job.handoff = None
                    raise

                preparing = None  # The returned stream is now explicitly owned by current.
                if current is None:
                    break
                if job.cancelled or not output.is_active(identity.output_id):
                    raise asyncio.CancelledError
                if current.first is not None and job.phase == OutputMessagePhase.FINAL_ANSWER:
                    await self._handoff.supersede(job)
                if not current.final and self._capacity > 1:
                    preparing = asyncio.create_task(
                        self._segments.prepare(job), name="speech_prepare"
                    )

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
                            self._segments.validate_frame(frame)
                            size += len(frame.data)
                            frames += 1
                            if (
                                samples + frame.samples_per_channel
                                > self._limits.audio_seconds * frame.sample_rate
                                or size > self._limits.audio_bytes
                                or frames > 4096
                            ):
                                raise RuntimeError("Speech segment exceeds its audio limit")

                            # No alignment, subtitle network or typing timer is awaited here.
                            stage = "audio_delivery"
                            job.audio_attempted = True
                            async with asyncio.timeout(self._limits.timeout):
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
                if preparing is None:
                    preparing = asyncio.create_task(
                        self._segments.prepare(job), name="speech_prepare"
                    )
        except asyncio.CancelledError:
            reason = job.cancel_reason or "synthesis_interrupted"
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
                try:
                    await self._handoff.reap(job, cancel=reason != "synthesis_completed")
                except Exception as error:
                    errors.append(error)
                if preparing is not None:
                    if not preparing.done():
                        preparing.cancel()
                    (result,) = await asyncio.gather(preparing, return_exceptions=True)
                    if isinstance(result, PreparedSpeech):
                        try:
                            await result.aclose()
                        except Exception as error:
                            errors.append(error)
                    elif isinstance(result, Exception) and result is not job.preparation_error:
                        errors.append(result)
                if abandoned is not None:
                    try:
                        await abandoned.aclose()
                    except Exception as error:
                        errors.append(error)
                try:
                    # Only source settlement waits for timing publication; PCM never does.
                    async with asyncio.timeout(self._limits.timeout):
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
                    await self.settle(identity, "speech_synthesis_failed" if errors else reason)
                except Exception as error:
                    errors.append(error)
                if errors:
                    raise ExceptionGroup("Speech streaming cleanup failed", errors)

            await wait_for_cleanup(asyncio.create_task(settle(), name="speech_settlement"))
