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
    OutputPlayback,
    OutputTextAudioAlignment,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Transcript:
    output_id: str
    lane: OutputLane
    turn_id: str | None
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
    """Release complete aligned phrases using transport progress, not generated text.

    Synthesis and playback terminal events are independent. Interruption cannot
    finalize the transcript before already-produced alignments have been consumed.
    """

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

    @property
    def name(self) -> str:
        return "transcript_synchronization"

    @staticmethod
    def _observe(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("Transcript consumer failed", exc_info=task.exception())

    def _state(self, event: OutputEvent) -> _Transcript | None:
        output = self._runtime.output
        output_id = event.output_id
        if not output_id or output.text_mode(output_id) != OutputTextMode.AUDIO_SYNCED:
            return None
        if output.transcript_finalized(output_id):
            return None
        identity = output.output_identity(output_id)
        if identity is None:
            return None
        lane, turn_id = identity
        state = self._states.get(output_id)
        if state is None:
            if len(self._states) >= self._capacity:
                raise RuntimeError("Transcript output capacity exhausted")
            state = _Transcript(output_id, lane, turn_id)
            self._states[output_id] = state
        elif (state.lane, state.turn_id) != identity:
            raise ValueError("Transcript output identity changed")
        return state

    async def _emit(self, state: _Transcript) -> None:
        # Phrase-level timing is deliberately conservative; no inferred word-level receipt.
        for alignment_id, value in state.alignments.items():
            if alignment_id in state.emitted or value.partial:
                continue

            if state.played + 1e-8 < value.end_time_sec:
                break

            event = await self._runtime.output.publish_transcript_chunk(
                text=value.text,
                output_id=state.output_id,
                turn_id=state.turn_id,
                lane=state.lane,
                source_chunk_id=value.source_chunk_id,
                start_time_sec=value.start_time_sec,
                end_time_sec=value.end_time_sec,
                is_first=not state.started,
                metadata={
                    "timing_source": value.timing_source,
                    "alignment_id": alignment_id,
                    "source_chunk_ids": value.source_chunk_ids,
                },
            )
            if event is not None:
                state.started = True
                state.emitted.add(alignment_id)

    async def _finish(self, state: _Transcript) -> None:
        await self._emit(state)
        if not state.audio_complete:
            return
        if state.alignment_sequence < state.expected_alignment_sequence:
            return
        if state.last_audio_sequence and not state.playback_complete:
            return

        await self._runtime.output.publish_transcript_chunk(
            text="",
            output_id=state.output_id,
            turn_id=state.turn_id,
            lane=state.lane,
            is_first=not state.started,
            is_final=True,
            interrupted=state.interrupted,
            end_time_sec=state.played,
            metadata={"measurement": "local_audio_queue", "timing_granularity": "phrase"},
        )
        self._states.pop(state.output_id, None)

    async def _handle(self, event: OutputEvent) -> None:
        payload = event.payload
        if isinstance(payload, OutputControl) and payload.type == OutputControlType.INTERRUPT:
            for output_id in event.metadata.get("interrupted_output_ids", ()):
                state = self._states.get(output_id)
                if state is not None:
                    state.interrupted = True

            return

        state = self._state(event)
        if state is None:
            return

        if isinstance(payload, OutputTextAudioAlignment):
            identity = payload.alignment_id or payload.source_chunk_id
            previous = state.alignments.get(identity)
            if previous is not None and previous != payload:
                raise ValueError("Conflicting text/audio alignment replay")

            state.alignments[identity] = payload
            state.alignment_sequence = max(state.alignment_sequence, event.sequence)
        elif isinstance(payload, OutputPlayback):
            state.played = max(state.played, payload.played_duration_sec)
            if payload.type in {OutputPlaybackType.FINISHED, OutputPlaybackType.INTERRUPTED}:
                state.playback_complete = True
                state.interrupted = (
                    state.interrupted or payload.type == OutputPlaybackType.INTERRUPTED
                )
        elif (
            isinstance(payload, OutputControl) and payload.type == OutputControlType.AUDIO_COMPLETE
        ):
            state.audio_complete = True
            state.last_audio_sequence = event.metadata["last_audio_sequence"]
            state.expected_alignment_sequence = event.metadata["last_alignment_sequence"]
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
            await asyncio.gather(self._start_task, return_exceptions=True)

        if self._task is not None:
            self._task.cancel()
        if self._subscription is not None:
            await self._runtime.output.stream.unsubscribe(self.CONSUMER_ID)
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

        # No fabricated text during shutdown. Retain only previously confirmed phrase output.
        for state in tuple(self._states.values()):
            await self._runtime.output.publish_transcript_chunk(
                text="",
                output_id=state.output_id,
                turn_id=state.turn_id,
                lane=state.lane,
                is_first=not state.started,
                is_final=True,
                interrupted=True,
                end_time_sec=state.played,
                metadata={"reason": "transcript_stopping"},
            )

        self._states.clear()
        self._subscription = self._task = None

    async def stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="transcript_close")
        await wait_for_cleanup(self._close_task)
