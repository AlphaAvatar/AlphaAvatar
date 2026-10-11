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
from dataclasses import dataclass, field
from math import isfinite

from livekit import rtc

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvOutput
from alphaavatar.core.media import AudioFrame
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.output.enums import (
    OutputControlType,
    OutputKind,
    OutputLane,
    OutputPlaybackType,
)
from alphaavatar.core.output.schemas import (
    OutputControl,
    OutputEvent,
    OutputIdentity,
    OutputPlayback,
    OutputSource,
)

from .codec import to_livekit_audio_frame

logger = logging.getLogger(__name__)
_SOURCE = OutputSource("rtc.livekit.audio")


@dataclass(slots=True)
class _Playout:
    identity: OutputIdentity
    frames: asyncio.Queue[OutputEvent] = field(default_factory=lambda: asyncio.Queue(maxsize=64))
    received_sequence: int = 0
    expected_sequence: int | None = None
    cancelled: bool = False
    queued: bool = False
    pushed: float = 0.0
    played: float = 0.0
    started: bool = False
    interrupted_played: float | None = None
    interrupted_queued: float = 0.0
    task: asyncio.Task | None = None
    running: bool = False


class LiveKitTransientAudioOutput:
    """Single-track assistant/transient transport; receipts measure the local queue only.

    The existing Host constructor name remains until native Engine integration.
    This adapter does not use an SDK AgentSession.
    """

    def __init__(
        self,
        *,
        room: rtc.Room,
        output_runtime: OutputRuntime,
        sample_rate: int,
        num_channels: int,
        track_name: str = "alphaavatar_transient_audio",
        queue_size_ms: int = 100,
        progress_interval_sec: float = 0.1,
        subscription_name: str = "livekit:transient_audio",
        lanes: tuple[OutputLane, ...] = (OutputLane.TRANSIENT, OutputLane.ASSISTANT),
        capture_timeout: float = 3.0,
        max_pending_outputs: int = 16,
    ) -> None:
        if min(sample_rate, num_channels, queue_size_ms, max_pending_outputs) <= 0:
            raise ValueError("Audio format and queue limits must be positive")
        if not all(
            isfinite(value) and value > 0 for value in (progress_interval_sec, capture_timeout)
        ):
            raise ValueError("Audio timeouts must be positive and finite")

        self._room, self._output = room, output_runtime
        self._sample_rate, self._num_channels = sample_rate, num_channels
        self._track_name, self._queue_ms = track_name, queue_size_ms
        self._interval, self._capture_timeout = progress_interval_sec, capture_timeout
        self._name, self._lanes, self._max_outputs = subscription_name, lanes, max_pending_outputs
        self._source = self._track = self._audio_sub = self._control_sub = None
        self._publication_sid: str | None = None
        self._jobs: dict[str, _Playout] = {}
        self._ready: asyncio.Queue[_Playout] = asyncio.Queue(maxsize=max_pending_outputs)
        self._active: _Playout | None = None
        self._tasks: list[asyncio.Task] = []
        self._start_task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None

    @property
    def track_sid(self) -> str | None:
        return self._publication_sid

    def _job(self, event: OutputEvent) -> _Playout:
        output = event.output
        identity = OutputIdentity(output.output_id, output.lane, output.scope)
        job = self._jobs.get(identity.output_id)
        if job is None:
            if len(self._jobs) >= self._max_outputs:
                raise RuntimeError("Audio output capacity exhausted")
            job = _Playout(identity)
            self._jobs[identity.output_id] = job
        elif job.identity != identity:
            raise ValueError("Audio output identity changed")
        return job

    def _cancel(self, job: _Playout) -> None:
        job.cancelled = True
        while not job.frames.empty():
            job.frames.get_nowait()

        if job is self._active and self._source is not None:
            if job.interrupted_played is None:
                queued = self._queued_duration()
                job.interrupted_played = min(job.pushed, max(job.played, job.pushed - queued))
                job.interrupted_queued = queued
            self._source.clear_queue()

        # A not-yet-started task must execute its finally and produce the unplayed receipt.
        if job.task is not None and job.running and not job.task.cancelling():
            job.task.cancel()

    async def _receipt(
        self,
        identity: OutputIdentity,
        kind: OutputPlaybackType,
        *,
        played: float,
        pushed: float,
        queued: float,
        measurement: str,
    ) -> OutputEvent | None:
        return await self._output.publish(
            EnvOutput(
                kind=OutputKind.PLAYBACK,
                output_id=identity.output_id,
                lane=identity.lane,
                scope=identity.scope,
                source=_SOURCE,
                payload=OutputPlayback(kind, played, pushed, queued),
                metadata={
                    "transport": "livekit",
                    "track_sid": self._publication_sid,
                    "measurement": measurement,
                },
            )
        )

    async def _unplayed(self, identity: OutputIdentity) -> None:
        await self._receipt(
            identity,
            OutputPlaybackType.INTERRUPTED,
            played=0.0,
            pushed=0.0,
            queued=0.0,
            measurement="not_started",
        )

    async def _reject(self, event: OutputEvent, reason: str) -> None:
        output_id = event.output.output_id
        logger.warning("Audio rejected output_id=%s reason=%s", output_id, reason)
        if output_id:
            await self._output.interrupt(output_id=output_id, reason=reason)
        job = self._jobs.get(output_id)
        if job is not None:
            self._cancel(job)

    async def _audio(self) -> None:
        while True:
            event = await self._audio_sub.get()
            output, frame = event.output, event.output.payload
            if not output.output_id or not self._output.can_deliver(output.output_id):
                continue
            if not isinstance(frame, AudioFrame):
                await self._reject(event, "invalid_audio_frame")
                continue
            if (frame.sample_rate, frame.num_channels) != (self._sample_rate, self._num_channels):
                await self._reject(event, "audio_format_mismatch")
                continue
            if frame.samples_per_channel <= 0 or frame.samples_per_channel > self._sample_rate:
                await self._reject(event, "audio_frame_size")
                continue
            try:
                job = self._job(event)
                if job.cancelled:
                    continue
                if not job.queued:
                    self._ready.put_nowait(job)
                    job.queued = True

                await job.frames.put(event)
                if job.cancelled or not self._output.can_deliver(job.identity.output_id):
                    self._cancel(job)
                    continue
                job.received_sequence = event.sequence
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._reject(event, "audio_queue_failed")

    async def _controls(self) -> None:
        while True:
            event = await self._control_sub.get()
            control = event.output.payload
            if not isinstance(control, OutputControl):
                continue
            if control.type == OutputControlType.INTERRUPT:
                for identity in control.targets:
                    if identity.lane not in self._lanes:
                        continue
                    job = self._jobs.get(identity.output_id)
                    if job is not None:
                        if job.identity != identity:
                            raise ValueError("Interrupted audio identity changed")
                        self._cancel(job)
                        if job.task is None:
                            await self._unplayed(identity)
                            self._jobs.pop(identity.output_id, None)
                    else:
                        await self._unplayed(identity)
            elif control.type == OutputControlType.COMPLETE and event.output.output_id:
                expected = control.barrier.last_audio_sequence
                if expected == 0 or not self._output.can_deliver(event.output.output_id):
                    continue
                try:
                    job = self._job(event)
                    job.expected_sequence = expected
                except Exception:
                    await self._reject(event, "audio_output_capacity")

    def _queued_duration(self) -> float:
        if self._source is None:
            return 0.0
        value = float(self._source.queued_duration)
        if not isfinite(value) or value < 0:
            raise RuntimeError("Invalid transport queue duration")
        return value

    async def _report(self, job: _Playout, kind: OutputPlaybackType) -> OutputEvent | None:
        queued = self._queued_duration()
        job.played = min(job.pushed, max(job.played, job.pushed - queued))
        return await self._receipt(
            job.identity,
            kind,
            played=job.played,
            pushed=job.pushed,
            queued=queued,
            measurement="local_audio_queue",
        )

    async def _drain(self, job: _Playout) -> None:
        waiter = asyncio.create_task(self._source.wait_for_playout(), name="audio_queue_drain")
        try:
            while not waiter.done():
                if job.cancelled or not self._output.can_deliver(job.identity.output_id):
                    raise asyncio.CancelledError
                done, _ = await asyncio.wait((waiter,), timeout=self._interval)
                if not done:
                    await self._report(job, OutputPlaybackType.PROGRESS)
            await waiter
        finally:
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    async def _play(self, job: _Playout) -> None:
        job.running, success = True, False
        try:
            while True:
                if job.cancelled or not self._output.can_deliver(job.identity.output_id):
                    raise asyncio.CancelledError

                if (
                    job.expected_sequence is not None
                    and job.received_sequence >= job.expected_sequence
                    and job.frames.empty()
                ):
                    await self._drain(job)
                    if job.cancelled or not self._output.can_deliver(job.identity.output_id):
                        raise asyncio.CancelledError
                    job.played = job.pushed

                    # Interruption can win admission after the last delivery check.
                    if await self._report(job, OutputPlaybackType.FINISHED) is None:
                        raise asyncio.CancelledError
                    success = True
                    return
                try:
                    event = await asyncio.wait_for(job.frames.get(), timeout=self._interval)
                except TimeoutError:
                    if job.started:
                        await self._report(job, OutputPlaybackType.PROGRESS)
                    continue
                if not self._output.can_deliver(job.identity.output_id):
                    raise asyncio.CancelledError
                frame = event.output.payload
                async with asyncio.timeout(self._capture_timeout):
                    await self._source.capture_frame(to_livekit_audio_frame(frame))
                if job.cancelled or not self._output.can_deliver(job.identity.output_id):
                    raise asyncio.CancelledError
                job.pushed += frame.samples_per_channel / frame.sample_rate
                kind = OutputPlaybackType.PROGRESS if job.started else OutputPlaybackType.STARTED
                job.started = True
                await self._report(job, kind)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Audio playout failed output_id=%s", job.identity.output_id)
        finally:
            try:
                if not success:

                    async def settle() -> None:
                        queued = self._queued_duration()
                        if job.interrupted_played is not None:
                            job.played, queued = job.interrupted_played, job.interrupted_queued
                        else:
                            job.played = min(job.pushed, max(job.played, job.pushed - queued))
                        self._source.clear_queue()
                        await self._output.interrupt(
                            output_id=job.identity.output_id, reason="audio_playout_stopped"
                        )
                        await self._receipt(
                            job.identity,
                            OutputPlaybackType.INTERRUPTED,
                            played=job.played,
                            pushed=job.pushed,
                            queued=queued,
                            measurement="local_audio_queue",
                        )

                    await wait_for_cleanup(asyncio.create_task(settle(), name="audio_settlement"))
            finally:
                # Local buffers must be released even when the failed stream rejects settlement.
                job.cancelled = True
                while not job.frames.empty():
                    job.frames.get_nowait()

    async def _playout(self) -> None:
        while True:
            job = await self._ready.get()
            if job.cancelled:
                continue
            self._active = job
            job.task = asyncio.create_task(self._play(job), name=f"audio:{job.identity.output_id}")
            try:
                await asyncio.shield(job.task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            finally:
                if job.task.done():
                    self._jobs.pop(job.identity.output_id, None)
                    self._active = None

    @staticmethod
    def _observe(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("Audio transport task failed", exc_info=task.exception())

    async def _start(self) -> None:
        self._source = rtc.AudioSource(
            sample_rate=self._sample_rate,
            num_channels=self._num_channels,
            queue_size_ms=self._queue_ms,
        )
        self._track = rtc.LocalAudioTrack.create_audio_track(self._track_name, self._source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE
        publication = await self._room.local_participant.publish_track(self._track, options)
        self._publication_sid = publication.sid
        self._audio_sub = await self._output.stream.subscribe(
            self._name,
            kinds=(OutputKind.AUDIO_FRAME,),
            lanes=self._lanes,
            max_pending=64,
            reliable=True,
        )
        self._control_sub = await self._output.stream.subscribe(
            f"{self._name}:control",
            kinds=(OutputKind.CONTROL,),
            lanes=self._lanes,
            max_pending=64,
            reliable=True,
        )

        for name, operation in (
            ("audio_intake", self._audio()),
            ("audio_control", self._controls()),
            ("audio_playout", self._playout()),
        ):
            task = asyncio.create_task(operation, name=name)
            task.add_done_callback(self._observe)
            self._tasks.append(task)

    async def on_session_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Audio output is closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="audio_start")
        try:
            await asyncio.shield(self._start_task)
        except BaseException as original:
            try:
                await self.on_session_stop()
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
        for suffix, subscription in (("", self._audio_sub), (":control", self._control_sub)):
            if subscription is not None:
                await self._output.stream.unsubscribe(self._name + suffix)

        await asyncio.gather(*self._tasks, return_exceptions=True)
        await asyncio.gather(
            *(job.task for job in jobs if job.task is not None), return_exceptions=True
        )

        errors = []
        for job in jobs:
            if job.task is None:
                try:
                    await self._output.interrupt(
                        output_id=job.identity.output_id, reason="audio_output_stopping"
                    )
                    await self._unplayed(job.identity)
                except Exception as exc:
                    errors.append(exc)
        self._jobs.clear()
        while not self._ready.empty():
            self._ready.get_nowait()
        self._active = None
        self._tasks.clear()
        if self._publication_sid is not None:
            try:
                await self._room.local_participant.unpublish_track(self._publication_sid)
            except Exception as exc:
                errors.append(exc)
        if self._source is not None:
            try:
                self._source.clear_queue()
                await self._source.aclose()
            except Exception as exc:
                errors.append(exc)
        self._source = self._track = self._audio_sub = self._control_sub = None
        self._publication_sid = None
        if errors:
            raise ExceptionGroup("Audio transport cleanup failed", errors)

    async def on_session_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="audio_close")
        await wait_for_cleanup(self._close_task)
