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
from math import ceil
from typing import TYPE_CHECKING

from alphaavatar.agents.avatar.voice import TTSBase
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.media import AudioFrame
from alphaavatar.core.output.enums import OutputKind, OutputPlaybackType
from alphaavatar.core.output.schemas import OutputPlayback

from ..speech_text import segment_target, text_weight
from .state import PreparedSpeech, SpeechJob, SpeechLimits

if TYPE_CHECKING:
    from alphaavatar.core.output.runtime import OutputRuntime

logger = logging.getLogger(__name__)


class SegmentPreparer:
    """Choose stable text boundaries and acquire one first frame; never own the Provider."""

    def __init__(self, output: OutputRuntime, tts: TTSBase | None, limits: SpeechLimits) -> None:
        self._output, self._tts, self._limits = output, tts, limits

    async def audio_margin(self, job: SpeechJob) -> float | None:
        # Optional pacing hint only. A lost/stale timeline entry must make preparation
        # more eager, never prevent speech or create another reliable media subscriber.
        output = self._output
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

    async def next_segment(self, job: SpeechJob) -> tuple[str, tuple[str, ...]]:
        clock, started = asyncio.get_running_loop().time, None
        first = job.segments == 0
        # A planning estimate stays below the existing duration/byte safety checks;
        # the actual PCM checks remain authoritative and are never relaxed here.
        audio_limit = self._limits.audio_seconds
        if self._tts is not None:
            audio_limit = min(
                audio_limit,
                self._limits.audio_bytes / (2 * self._tts.sample_rate * self._tts.num_channels),
            )

        while not job.cancelled and self._output.is_active(job.identity.output_id):
            maximum = min(
                self._limits.segment_chars, max(1, int(audio_limit * job.budget_rate * 0.8))
            )
            if first:
                maximum = min(maximum, 112)
            target = segment_target(job.segments, maximum)
            # Once the answer is complete, balance its remaining phrases instead of
            # manufacturing a tiny second segment followed by an oversized final one.
            if job.ended and not first:
                preview = job.peek(2 * maximum + 64)
                if len(preview) == job.pending_chars and preview:
                    units = text_weight(preview)
                    target = min(maximum, ceil(units / ceil(units / maximum)))
                else:
                    target = maximum
            minimum = min(self._limits.min_chars, target)
            job.changed.clear()
            if not job.pending_chars:
                if job.ended:
                    return "", ()
                await job.changed.wait()
                continue

            if started is None:
                started = clock()
            margin = await self.audio_margin(job) if not first else None
            if job.cancelled or not self._output.is_active(job.identity.output_id):
                raise asyncio.CancelledError
            if first:
                # Stable sentence boundaries can still release immediately. A short,
                # unfinished phrase gets the original collection window, not a forced
                # word cut at 180 ms that leaves a one-word TTS request behind.
                wait = self._limits.flush_interval
            elif margin is None:
                wait = min(self._limits.flush_interval, 0.15)
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

    async def prepare(self, job: SpeechJob) -> PreparedSpeech | None:
        text, chunks = await self.next_segment(job)
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
                self.validate_frame(first)
            if job.cancelled or not self._output.is_active(job.identity.output_id):
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
        return PreparedSpeech(
            text,
            chunks,
            stream,
            first,
            job.segments,
            job.ended and job.pending_chars == 0,
            elapsed * 1000,
        )

    def validate_frame(self, frame: AudioFrame) -> None:
        if not isinstance(frame, AudioFrame) or (frame.sample_rate, frame.num_channels) != (
            self._tts.sample_rate,
            self._tts.num_channels,
        ):
            raise ValueError("TTS audio format changed")
        if not 0 < frame.samples_per_channel <= frame.sample_rate:
            raise ValueError("Invalid TTS audio frame duration")
