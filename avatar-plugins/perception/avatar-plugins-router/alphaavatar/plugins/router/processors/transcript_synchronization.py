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

from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvOutput
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
    OutputTranscriptChunk,
)

logger = logging.getLogger(__name__)
_SOURCE = OutputSource("router.transcript_synchronization")


@dataclass(slots=True)
class _Transcript:
    identity: OutputIdentity
    alignments: dict[str, OutputTextAudioAlignment] = field(default_factory=dict)
    emitted: set[str] = field(default_factory=set)
    played: float = 0.0
    started: bool = False
    interrupted: bool = False
    audio_complete: bool = False
    last_audio_sequence: int = 0
    expected_alignment_sequence: int = 0
    alignment_sequence: int = 0
    playback_complete: bool = False


class TranscriptSynchronizationProcessor(RouterProcessorBase):
    """Release confirmed complete phrases; synthesis and playout are independent barriers."""

    CONSUMER_ID = "router.transcript_synchronization"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        lanes: tuple[OutputLane, ...] = (OutputLane.TRANSIENT, OutputLane.ASSISTANT),
        max_pending_outputs: int = 256,
    ) -> None:
        super().__init__(runtime=runtime)
        if max_pending_outputs < 1:
            raise ValueError("Transcript capacity must be positive")
        self._lanes, self._capacity = lanes, max_pending_outputs
        self._states: dict[str, _Transcript] = {}
        self._subscription = None
        self._task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None
        self._start_task: asyncio.Task | None = None
        self._worker_failures: list[Exception] = []
        self._observed_tasks: set[asyncio.Task] = set()
        self._stopped_tasks: set[asyncio.Task] = set()

    @property
    def name(self) -> str:
        return "transcript_synchronization"

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
            if task in self._stopped_tasks:
                return
            error = asyncio.CancelledError()
        elif (error := task.exception()) is None:
            if task in self._stopped_tasks:
                return
            error = RuntimeError(f"{self.CONSUMER_ID} worker exited unexpectedly")
        self._remember_failure(error, task.get_name())
        self._ensure_close()

    def _stop_worker(self, task: asyncio.Task) -> None:
        if task.done():
            self._observe(task)
        elif not task.cancelling():
            # Only a cancellation requested here is normal lifecycle shutdown.
            self._stopped_tasks.add(task)
            task.cancel()

    async def _retire_subscription(self) -> None:
        if self._subscription is None:
            return
        if self._worker_failures:
            # Keep a failed subscription registered until OutputRuntime closes. Removing it
            # would make later publications appear successful with a missing required consumer.
            await self._subscription.fail(self._worker_failures[0])
        else:
            await self._runtime.output.stream.unsubscribe(self.CONSUMER_ID)

    def _state(self, event: OutputEvent) -> _Transcript | None:
        output = self._runtime.output
        value = event.output
        output_id = value.output_id
        if (
            not output_id
            or output.text_mode(output_id) != OutputTextMode.AUDIO_SYNCED
            or output.transcript_finalized(output_id)
        ):
            return None
        identity = output.output_identity(output_id)
        if identity is None:
            return None
        if (value.scope, value.lane) != (identity.scope, identity.lane):
            raise ValueError("Transcript output identity changed")
        state = self._states.get(output_id)
        if state is None:
            if len(self._states) >= self._capacity:
                raise RuntimeError("Transcript output capacity exhausted")
            state = _Transcript(identity)
            self._states[output_id] = state
        elif state.identity != identity:
            raise ValueError("Transcript output identity changed")
        return state

    async def _emit(self, state: _Transcript) -> None:
        identity = state.identity
        for alignment_id, value in state.alignments.items():
            if alignment_id in state.emitted or value.partial:
                continue
            if state.played + 1e-8 < value.end_time_sec:
                break
            chunk = OutputTranscriptChunk(
                text=value.text,
                source_chunk_ids=value.source_chunk_ids,
                alignment_id=alignment_id,
                start_time_sec=value.start_time_sec,
                end_time_sec=value.end_time_sec,
                is_first=not state.started,
                timing_source=value.timing_source,
            )
            event = await self._runtime.output.publish(
                EnvOutput(
                    kind=OutputKind.TRANSCRIPT_CHUNK,
                    output_id=identity.output_id,
                    lane=identity.lane,
                    scope=identity.scope,
                    source=_SOURCE,
                    payload=chunk,
                )
            )
            if event is not None:
                state.started = True
                state.emitted.add(alignment_id)

    async def _final(self, state: _Transcript, *, reason: str | None = None) -> None:
        identity = state.identity
        await self._runtime.output.publish(
            EnvOutput(
                kind=OutputKind.TRANSCRIPT_CHUNK,
                output_id=identity.output_id,
                lane=identity.lane,
                scope=identity.scope,
                source=_SOURCE,
                payload=OutputTranscriptChunk(
                    text="",
                    is_first=not state.started,
                    is_final=True,
                    interrupted=state.interrupted or reason is not None,
                    end_time_sec=state.played,
                    reason=reason,
                ),
                metadata={"measurement": "local_audio_queue", "timing_granularity": "phrase"},
            )
        )

    async def _finish(self, state: _Transcript) -> None:
        await self._emit(state)
        if not state.audio_complete or state.alignment_sequence < state.expected_alignment_sequence:
            return
        if state.last_audio_sequence and not state.playback_complete:
            return
        await self._final(state)
        self._states.pop(state.identity.output_id, None)

    async def _handle(self, event: OutputEvent) -> None:
        payload = event.output.payload
        if isinstance(payload, OutputControl) and payload.type == OutputControlType.INTERRUPT:
            for identity in payload.targets:
                state = self._states.get(identity.output_id)
                if state is not None and state.identity == identity:
                    state.interrupted = True
            return

        state = self._state(event)
        if state is None:
            return

        if isinstance(payload, OutputTextAudioAlignment):
            previous = state.alignments.get(payload.alignment_id)
            if previous is not None and previous != payload:
                raise ValueError("Conflicting text/audio alignment replay")
            state.alignments[payload.alignment_id] = payload
            state.alignment_sequence = max(state.alignment_sequence, event.sequence)
        elif isinstance(payload, OutputPlayback):
            state.played = max(state.played, payload.played_duration_sec)
            if payload.type in (OutputPlaybackType.FINISHED, OutputPlaybackType.INTERRUPTED):
                state.playback_complete = True
                state.interrupted = (
                    state.interrupted or payload.type == OutputPlaybackType.INTERRUPTED
                )
        elif (
            isinstance(payload, OutputControl) and payload.type == OutputControlType.AUDIO_COMPLETE
        ):
            state.audio_complete = True
            state.last_audio_sequence = payload.barrier.last_audio_sequence
            state.expected_alignment_sequence = payload.barrier.last_alignment_sequence
            state.interrupted = state.interrupted or payload.reason != "synthesis_completed"
        await self._finish(state)

    async def _run(self) -> None:
        try:
            while True:
                await self._handle(await self._subscription.get())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Transcript synchronization stopped")
            raise

    async def _start(self) -> None:
        self._subscription = await self._runtime.output.stream.subscribe(
            self.CONSUMER_ID,
            kinds=(OutputKind.ALIGNMENT, OutputKind.PLAYBACK, OutputKind.CONTROL),
            lanes=self._lanes,
            max_pending=256,
            reliable=True,
        )
        self._task = asyncio.create_task(self._run(), name=self.CONSUMER_ID)
        self._task.add_done_callback(self._observe)

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
                self._remember_failure(result, "Transcript startup")

        worker = self._task
        if worker is not None:
            self._stop_worker(worker)
        try:
            # Wake blocked publishers before joining the worker or publishing final captions.
            await self._retire_subscription()
        except BaseException as error:
            self._remember_failure(error, "Transcript subscription retirement")
        if worker is not None:
            await asyncio.gather(worker, return_exceptions=True)
            self._observe(worker)

        try:
            results = await asyncio.gather(
                *(
                    self._final(state, reason="transcript_stopping")
                    for state in tuple(self._states.values())
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    self._remember_failure(result, "Transcript settlement")
        finally:
            self._states.clear()
            self._subscription = self._task = None
        if self._worker_failures:
            raise ExceptionGroup("Transcript synchronization cleanup failed", self._worker_failures)

    def _ensure_close(self) -> asyncio.Task:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name=f"{self.CONSUMER_ID}:close")
            self._close_task.add_done_callback(self._observe_close)
        return self._close_task

    async def stop(self) -> None:
        await wait_for_cleanup(self._ensure_close())
