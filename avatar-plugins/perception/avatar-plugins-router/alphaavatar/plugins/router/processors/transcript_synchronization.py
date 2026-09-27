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
"""Synchronize user-visible transcript with actual audio playout."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.output import (
    OutputControl,
    OutputControlType,
    OutputEvent,
    OutputKind,
    OutputLane,
    OutputPlayback,
    OutputPlaybackType,
    OutputSubscription,
    OutputTextAudioAlignment,
    OutputTextChunk,
    OutputTextMode,
)

from ..log import logger

_TOKEN_PATTERN = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]"
    r"|[^\W_]+(?:['’\-][^\W_]+)*"
    r"|[^\w\s]"
    r"|\s+",
    re.UNICODE,
)


@dataclass(slots=True)
class _AlignmentState:
    value: OutputTextAudioAlignment
    units: tuple[str, ...]
    weights: tuple[float, ...]
    delivered_units: int = 0

    @property
    def total_weight(self) -> float:
        return sum(self.weights)


@dataclass(slots=True)
class _TranscriptState:
    output_id: str
    lane: OutputLane
    turn_id: str | None
    source_chunks: dict[str, OutputTextChunk] = field(default_factory=dict)
    alignments: dict[str, _AlignmentState] = field(default_factory=dict)
    alignment_order: list[str] = field(default_factory=list)
    played_duration_sec: float = 0.0
    playback_started: bool = False
    source_complete: bool = False
    interrupt_requested: bool = False
    transcript_started: bool = False
    finalized: bool = False


class TranscriptSynchronizationProcessor(RouterProcessorBase):
    """
    Convert AUDIO_SYNCED source text into delivered transcript chunks.

    Text is released only according to actual PLAYBACK progress. An interrupt
    keeps already published transcript and prevents unplayed text from being
    emitted.
    """

    CONSUMER_ID = "router.transcript_synchronization"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        lanes: tuple[OutputLane, ...] = (OutputLane.TRANSIENT,),
    ) -> None:
        super().__init__(runtime=runtime)

        self._lanes = lanes
        self._subscription: OutputSubscription | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._states: dict[str, _TranscriptState] = {}
        self._started = False

    @property
    def name(self) -> str:
        return "transcript_synchronization"

    @staticmethod
    def _matches_control(state: _TranscriptState, control: OutputControl) -> bool:
        if control.target_output_id is not None and state.output_id != control.target_output_id:
            return False
        if control.target_lane is not None and state.lane != control.target_lane:
            return False
        if control.target_turn_id is not None and state.turn_id != control.target_turn_id:
            return False
        return True

    @staticmethod
    def _split_units(text: str) -> tuple[str, ...]:
        raw_tokens = _TOKEN_PATTERN.findall(text)
        units: list[str] = []
        pending_space = ""

        for token in raw_tokens:
            if token.isspace():
                pending_space += token
            elif (
                TranscriptSynchronizationProcessor._is_punctuation(token)
                and units
                and not pending_space
            ):
                units[-1] += token
            else:
                units.append(pending_space + token)
                pending_space = ""

        if pending_space:
            if units:
                units[-1] += pending_space
            else:
                units.append(pending_space)

        return tuple(units)

    @staticmethod
    def _is_punctuation(token: str) -> bool:
        return bool(token) and all(not char.isalnum() and not char.isspace() for char in token)

    @staticmethod
    def _unit_weight(unit: str) -> float:
        visible_length = len(unit.strip())
        return float(max(visible_length, 1))

    @staticmethod
    def _target_unit_count(alignment: _AlignmentState, ratio: float) -> int:
        if ratio >= 1.0:
            return len(alignment.units)
        if ratio <= 0.0 or alignment.total_weight <= 0:
            return 0

        threshold = alignment.total_weight * ratio
        accumulated = 0.0
        count = 0

        for weight in alignment.weights:
            if accumulated + weight > threshold:
                break
            accumulated += weight
            count += 1

        return count

    @staticmethod
    def _weight_ratio(alignment: _AlignmentState, unit_count: int) -> float:
        if alignment.total_weight <= 0:
            return 0.0
        return min(sum(alignment.weights[:unit_count]) / alignment.total_weight, 1.0)

    async def _run(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return

        try:
            while True:
                event = await subscription.get()

                try:
                    if event.kind == OutputKind.TEXT_CHUNK:
                        await self._handle_text(event)
                    elif event.kind == OutputKind.ALIGNMENT:
                        await self._handle_alignment(event)
                    elif event.kind == OutputKind.PLAYBACK:
                        await self._handle_playback(event)
                    elif event.kind == OutputKind.CONTROL:
                        await self._handle_control(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Failed to synchronize transcript event_id=%s output_id=%s kind=%s",
                        event.event_id,
                        event.output_id,
                        event.kind,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Transcript synchronization processor stopped unexpectedly.")

    async def _handle_text(self, event: OutputEvent) -> None:
        payload = event.payload
        if not isinstance(payload, OutputTextChunk):
            return
        if payload.mode != OutputTextMode.AUDIO_SYNCED:
            return

        state = self._state_for(event)
        state.source_chunks[payload.chunk_id] = payload

    async def _handle_alignment(self, event: OutputEvent) -> None:
        payload = event.payload
        if not isinstance(payload, OutputTextAudioAlignment):
            return

        state = self._state_for(event)
        units = self._split_units(payload.text)
        weights = tuple(self._unit_weight(unit) for unit in units)

        if payload.source_chunk_id not in state.alignments:
            state.alignment_order.append(payload.source_chunk_id)

        state.alignments[payload.source_chunk_id] = _AlignmentState(
            value=payload,
            units=units,
            weights=weights,
        )
        await self._emit_due(state)

    async def _handle_playback(self, event: OutputEvent) -> None:
        payload = event.payload
        if not isinstance(payload, OutputPlayback):
            return

        state = self._state_for(event)
        state.played_duration_sec = max(state.played_duration_sec, payload.played_duration_sec)

        if payload.type == OutputPlaybackType.STARTED:
            state.playback_started = True
            await self._emit_due(state)
        elif payload.type == OutputPlaybackType.PROGRESS:
            state.playback_started = True
            await self._emit_due(state)
        elif payload.type == OutputPlaybackType.FINISHED:
            state.playback_started = True
            await self._emit_due(state, force_all=True)
            await self._finalize(state, interrupted=False)
        elif payload.type == OutputPlaybackType.INTERRUPTED:
            await self._emit_due(state)
            await self._finalize(state, interrupted=True)

    async def _handle_control(self, event: OutputEvent) -> None:
        control = event.payload
        if not isinstance(control, OutputControl):
            return

        states = tuple(
            state for state in self._states.values() if self._matches_control(state, control)
        )

        if control.type == OutputControlType.COMPLETE:
            for state in states:
                state.source_complete = True
            return

        if control.type != OutputControlType.INTERRUPT:
            return

        for state in states:
            state.interrupt_requested = True

            # No playback means no user-visible text was delivered.
            if not state.playback_started:
                await self._finalize(state, interrupted=True)

    async def _emit_due(self, state: _TranscriptState, *, force_all: bool = False) -> None:
        if state.finalized:
            return

        for source_chunk_id in state.alignment_order:
            alignment = state.alignments[source_chunk_id]
            value = alignment.value

            if not alignment.units:
                continue
            if not force_all and state.played_duration_sec <= value.start_time_sec:
                continue

            duration = max(value.duration_sec, 1e-6)
            ratio = (
                1.0
                if force_all
                else min(
                    max((state.played_duration_sec - value.start_time_sec) / duration, 0.0),
                    1.0,
                )
            )
            target_units = self._target_unit_count(alignment, ratio)

            if target_units <= alignment.delivered_units:
                continue

            start_unit = alignment.delivered_units
            text = "".join(alignment.units[start_unit:target_units])
            start_ratio = self._weight_ratio(alignment, start_unit)
            end_ratio = self._weight_ratio(alignment, target_units)

            published = await self._runtime.output.publish_transcript_chunk(
                text=text,
                output_id=state.output_id,
                turn_id=state.turn_id,
                lane=state.lane,
                source_chunk_id=source_chunk_id,
                start_time_sec=value.start_time_sec + duration * start_ratio,
                end_time_sec=value.start_time_sec + duration * end_ratio,
                is_first=not state.transcript_started,
                is_final=False,
                interrupted=False,
                metadata={
                    "timing_source": value.timing_source,
                    "partial_alignment": value.partial,
                },
            )

            if published is not None:
                state.transcript_started = True
                alignment.delivered_units = target_units

    async def _finalize(self, state: _TranscriptState, *, interrupted: bool) -> None:
        if state.finalized:
            return

        state.finalized = True

        await self._runtime.output.publish_transcript_chunk(
            text="",
            output_id=state.output_id,
            turn_id=state.turn_id,
            lane=state.lane,
            is_first=not state.transcript_started,
            is_final=True,
            interrupted=interrupted,
            end_time_sec=state.played_duration_sec,
            metadata={
                "source_complete": state.source_complete,
                "interrupt_requested": state.interrupt_requested,
            },
        )
        self._states.pop(state.output_id, None)

    def _state_for(self, event: OutputEvent) -> _TranscriptState:
        output_id = event.output_id
        if not output_id:
            raise ValueError("Transcript event requires output_id")

        state = self._states.get(output_id)
        if state is None:
            state = _TranscriptState(
                output_id=output_id,
                lane=event.lane,
                turn_id=event.turn_id,
            )
            self._states[output_id] = state
        elif state.lane != event.lane or state.turn_id != event.turn_id:
            raise ValueError(f"Transcript identity mismatch output_id={output_id!r}")

        return state

    async def start(self) -> None:
        if self._started:
            return

        self._subscription = await self._runtime.output.stream.subscribe(
            self.CONSUMER_ID,
            kinds=(
                OutputKind.TEXT_CHUNK,
                OutputKind.ALIGNMENT,
                OutputKind.PLAYBACK,
                OutputKind.CONTROL,
            ),
            lanes=self._lanes,
            max_pending=256,
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

        if self._subscription is not None:
            await self._runtime.output.stream.unsubscribe(self.CONSUMER_ID)

        self._subscription = None
        self._states.clear()
