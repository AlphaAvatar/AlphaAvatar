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
from dataclasses import replace
from math import isfinite

from alphaavatar.agents.avatar.voice import TTSBase
from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.output.enums import OutputControlType, OutputKind, OutputLane, OutputTextMode
from alphaavatar.core.output.schemas import (
    OutputControl,
    OutputEvent,
    OutputIdentity,
    OutputTextChunk,
)

from .handoff import AnswerHandoff
from .segmentation import SegmentPreparer
from .state import SpeechJob, SpeechLimits
from .streaming import SpeechStreamer

logger = logging.getLogger(__name__)


class SpeechSynthesisProcessor(RouterProcessorBase):
    """Own intake, scheduling and shutdown; helpers share its bounded job registry."""

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
        self._tts_capacity = tts.max_concurrent_streams if tts is not None else 1
        if type(self._tts_capacity) is not int or self._tts_capacity < 1:
            raise ValueError("TTS stream capacity must be a positive integer")
        self._max_outputs, self._max_chars = max_pending_outputs, max_pending_chars
        self._jobs: OrderedDict[str, SpeechJob] = OrderedDict()
        self._wake = asyncio.Event()
        self._subscription = None
        self._tasks: list[asyncio.Task] = []
        self._close_task: asyncio.Task | None = None
        self._start_task: asyncio.Task | None = None
        self._worker_failures: list[Exception] = []
        self._observed_tasks: set[asyncio.Task] = set()
        self._stopped_tasks: set[asyncio.Task] = set()
        self._externally_cancelled_tasks: set[asyncio.Task] = set()
        limits = SpeechLimits(
            max_outputs=max_pending_outputs,
            max_chars=max_pending_chars,
            segment_chars=segment_chars,
            min_chars=min_segment_chars,
            flush_interval=flush_interval,
            timeout=delivery_timeout,
            audio_seconds=max_segment_audio_seconds,
            audio_bytes=max_segment_audio_bytes,
        )
        self._segments = SegmentPreparer(runtime.output, tts, limits)
        self._handoff = AnswerHandoff(
            output=runtime.output,
            jobs=self._jobs,
            segments=self._segments,
            wake=self._wake,
            cancel=self._cancel,
            capacity=self._tts_capacity,
            limits=limits,
        )
        self._streamer = SpeechStreamer(
            output=runtime.output,
            tts=tts,
            segments=self._segments,
            handoff=self._handoff,
            capacity=self._tts_capacity,
            limits=limits,
        )

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

    def _cancel(self, job: SpeechJob, *, reason: str | None = None) -> None:
        if reason is not None and not job.cancelled:
            job.cancel_reason = reason
        job.cancelled = True
        job.pieces.clear()
        job.pending_chars = 0
        job.changed.set()
        if job.task is not None and job.running and not job.task.cancelling():
            job.task.cancel()
        if job.handoff is not None and not job.handoff.done() and not job.handoff.cancelling():
            job.handoff.cancel()
        self._wake.set()

    async def _reject(self, event: OutputEvent, reason: str) -> None:
        value = event.output
        job = self._jobs.get(value.output_id)
        if job is None:
            identity = OutputIdentity(value.output_id, value.lane, value.scope)
            await wait_for_cleanup(
                asyncio.create_task(
                    self._streamer.settle(identity, reason), name="speech_rejection"
                )
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

            job = SpeechJob(
                identity,
                replace(output.source, producer="router.speech_synthesis"),
                output.metadata,
                phase=chunk.phase,
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

        if chunk.phase is not None:
            job.phase = chunk.phase
        job.append(chunk)
        self._handoff.plan(job)
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
                    self._cancel(job, reason=control.reason)
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
                phase = control.phase
                if phase is not None:
                    if job.phase is not None and job.phase != phase:
                        raise ValueError("Speech message phase changed")
                    job.phase = phase
                job.ended = True
                job.changed.set()
                self._handoff.plan(job)

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

    async def _synthesize(self) -> None:
        while True:
            self._wake.clear()
            if not self._jobs:
                await self._wake.wait()
                continue

            job = next(iter(self._jobs.values()))
            job.task = asyncio.create_task(
                self._streamer.run(job), name=f"tts:{job.identity.output_id}"
            )
            try:
                await asyncio.shield(job.task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            finally:
                if job.task.done():
                    self._jobs.pop(job.identity.output_id, None)

    async def _start(self) -> None:
        if self._tts is not None:
            self._tts.prewarm()

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

        async def settle_unstarted(job: SpeechJob) -> None:
            try:
                await self._handoff.reap(job)
            finally:
                reason = (
                    "speech_synthesis_failed"
                    if job.preparation_error is not None
                    else "speech_synthesis_stopping"
                )
                await self._streamer.settle(job.identity, reason)

        try:
            results = await asyncio.gather(
                *(settle_unstarted(job) for job in jobs if job.task is None), return_exceptions=True
            )
            for result in results:
                if isinstance(result, BaseException):
                    self._remember_failure(result, "Unstarted speech settlement")
        finally:
            self._jobs.clear()
            self._handoff.clear()
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
