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
"""Session-scoped, time-aligned output runtime."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from uuid import uuid4

from alphaavatar.core.media import AudioFrame

from .schema import (
    OutputControl,
    OutputControlType,
    OutputEvent,
    OutputKind,
    OutputLane,
    OutputPlayback,
    OutputPlaybackType,
    OutputTextAudioAlignment,
    OutputTextChunk,
    OutputTextMode,
    OutputTranscriptChunk,
)
from .stream import OutputStream
from .timeline import OutputTimeline


@dataclass(slots=True)
class _OutputRecord:
    lane: OutputLane
    turn_id: str | None
    origin_kind: OutputKind
    terminal: OutputControlType | None = None
    playback: OutputPlaybackType | None = None
    text_started: bool = False

    @property
    def active(self) -> bool:
        """Whether the source may still produce new text or audio."""
        return self.terminal is None

    @property
    def interruptible(self) -> bool:
        """Whether queued or playing output can still be interrupted."""
        return self.terminal != OutputControlType.INTERRUPT and self.playback not in {
            OutputPlaybackType.FINISHED,
            OutputPlaybackType.INTERRUPTED,
        }


class OutputRuntime:
    """
    Session output composition root.

    output_id identifies one complete logical message.
    turn_id groups outputs belonging to the same interaction turn.

    A new output_id may replace another active output in the same lane.
    Additional chunks using the same output_id append to the existing output.
    Interrupted or completed output IDs can never be reopened.
    """

    def __init__(self, *, session_id: str, timeline_max_items: int = 4096) -> None:
        if not session_id:
            raise ValueError("OutputRuntime requires a non-empty session_id")

        self.session_id = session_id
        self.stream = OutputStream()
        self.timeline = OutputTimeline(max_items=timeline_max_items)

        self._sequence = 0
        self._sequence_lock = asyncio.Lock()

        self._outputs: dict[str, _OutputRecord] = {}
        self._state_lock = asyncio.Lock()

        # Serializes logical output creation and lane replacement. It does not
        # block the event loop; competing publishers await asynchronously.
        self._open_lock = asyncio.Lock()
        self._closed = False

    @staticmethod
    def _validate_output(
        record: _OutputRecord,
        *,
        output_id: str,
        lane: OutputLane,
        turn_id: str | None,
    ) -> None:
        if record.lane != lane:
            raise ValueError(
                f"Output lane mismatch output_id={output_id!r}: "
                f"existing={record.lane!r}, requested={lane!r}"
            )

        if record.turn_id != turn_id:
            raise ValueError(
                f"Output turn mismatch output_id={output_id!r}: "
                f"existing={record.turn_id!r}, requested={turn_id!r}"
            )

    async def _get_output(self, output_id: str) -> _OutputRecord | None:
        async with self._state_lock:
            return self._outputs.get(output_id)

    async def _get_or_create_output(
        self,
        *,
        output_id: str,
        lane: OutputLane,
        turn_id: str | None,
        origin_kind: OutputKind,
    ) -> tuple[_OutputRecord | None, bool]:
        async with self._state_lock:
            if self._closed:
                raise RuntimeError("OutputRuntime is closed")

            record = self._outputs.get(output_id)
            if record is not None:
                self._validate_output(record, output_id=output_id, lane=lane, turn_id=turn_id)
                return (record if record.active else None), False

            record = _OutputRecord(lane=lane, turn_id=turn_id, origin_kind=origin_kind)
            self._outputs[output_id] = record
            return record, True

    async def _prepare_output(
        self,
        *,
        output_id: str,
        lane: OutputLane,
        turn_id: str | None,
        origin_kind: OutputKind,
        replace_lane: bool,
        replace_reason: str,
        preempt_transient: bool = False,
    ) -> tuple[_OutputRecord | None, bool]:
        """
        Resolve one logical output.

        Existing active output_id:
            append to it without interruption.

        Existing terminal output_id:
            reject it; output IDs cannot be reopened.

        New output_id:
            optionally interrupt active output in the same lane before opening.
        """
        async with self._open_lock:
            existing = await self._get_output(output_id)
            if existing is not None:
                self._validate_output(
                    existing,
                    output_id=output_id,
                    lane=lane,
                    turn_id=turn_id,
                )
                return (existing if existing.active else None), False

            if replace_lane:
                await self.interrupt(
                    lane=lane,
                    reason=replace_reason,
                    metadata={
                        "replacement_output_id": output_id,
                        "replacement_turn_id": turn_id,
                    },
                )

            # A formal assistant message also replaces transient filler/status
            # speech, independently of whether another assistant output exists.
            if preempt_transient and lane != OutputLane.TRANSIENT:
                await self.interrupt(
                    lane=OutputLane.TRANSIENT,
                    reason="assistant_output_started",
                    metadata={
                        "assistant_output_id": output_id,
                        "turn_id": turn_id,
                    },
                )

            return await self._get_or_create_output(
                output_id=output_id,
                lane=lane,
                turn_id=turn_id,
                origin_kind=origin_kind,
            )

    async def _publish(
        self,
        *,
        kind: OutputKind,
        lane: OutputLane,
        output_id: str | None,
        turn_id: str | None,
        payload,
        metadata: dict | None,
    ) -> OutputEvent:
        if self._closed:
            raise RuntimeError("OutputRuntime is closed")

        async with self._sequence_lock:
            self._sequence += 1
            event = OutputEvent(
                event_id=uuid4().hex,
                sequence=self._sequence,
                session_id=self.session_id,
                created_at=time.time(),
                monotonic_ns=time.monotonic_ns(),
                kind=kind,
                lane=lane,
                output_id=output_id,
                turn_id=turn_id,
                payload=payload,
                metadata=dict(metadata or {}),
            )
            await self.timeline.append(event)

        await self.stream.publish(event)
        return event

    def is_active(self, output_id: str) -> bool:
        record = self._outputs.get(output_id)
        return record is not None and record.active

    async def start_turn(self, *, turn_id: str) -> None:
        """Stop transient output left by the preceding interaction state."""
        await self.interrupt(
            lane=OutputLane.TRANSIENT,
            reason="new_turn_started",
            metadata={"new_turn_id": turn_id},
        )

    async def publish_status(
        self,
        *,
        payload: dict,
        turn_id: str | None,
        metadata: dict | None = None,
    ) -> OutputEvent:
        return await self._publish(
            kind=OutputKind.STATUS,
            lane=OutputLane.STATUS,
            output_id=None,
            turn_id=turn_id,
            payload=payload,
            metadata=metadata,
        )

    async def request_speech(
        self,
        *,
        text: str,
        lane: OutputLane = OutputLane.TRANSIENT,
        output_id: str | None = None,
        turn_id: str | None = None,
        replace_lane: bool = True,
        is_final: bool = True,
        metadata: dict | None = None,
    ) -> OutputEvent | None:
        text = text.strip()
        if not text:
            raise ValueError("Speech request requires non-empty text")

        resolved_output_id = output_id or uuid4().hex
        record, created = await self._prepare_output(
            output_id=resolved_output_id,
            lane=lane,
            turn_id=turn_id,
            origin_kind=OutputKind.SPEECH_REQUEST,
            replace_lane=replace_lane,
            replace_reason="replaced_by_new_speech_request",
        )
        if record is None:
            return None

        return await self._publish(
            kind=OutputKind.SPEECH_REQUEST,
            lane=lane,
            output_id=resolved_output_id,
            turn_id=turn_id,
            payload={
                "text": text,
                "chunk_id": uuid4().hex,
                "is_first": created,
                "is_final": is_final,
            },
            metadata=metadata,
        )

    async def publish_text_chunk(
        self,
        *,
        text: str,
        output_id: str,
        turn_id: str | None,
        lane: OutputLane = OutputLane.ASSISTANT,
        chunk_id: str | None = None,
        mode: OutputTextMode = OutputTextMode.MIRROR,
        replace_lane: bool = True,
        is_final: bool = False,
        metadata: dict | None = None,
    ) -> OutputEvent | None:
        """
        Publish one source-text chunk.

        Same output_id:
            append to the existing logical message.

        New output_id:
            replace the current output in the same lane when replace_lane=True.

        New assistant output:
            also interrupt active transient output before publication.
        """
        if text == "":
            return None

        record, created = await self._prepare_output(
            output_id=output_id,
            lane=lane,
            turn_id=turn_id,
            origin_kind=OutputKind.TEXT_CHUNK,
            replace_lane=replace_lane,
            replace_reason="replaced_by_new_text_output",
            preempt_transient=lane == OutputLane.ASSISTANT,
        )
        if record is None:
            return None

        async with self._state_lock:
            if not record.active:
                return None

            first_chunk = not record.text_started
            if first_chunk:
                record.text_started = True

        return await self._publish(
            kind=OutputKind.TEXT_CHUNK,
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputTextChunk(
                text=text,
                chunk_id=chunk_id or uuid4().hex,
                is_first=first_chunk,
                is_final=is_final,
                mode=mode,
            ),
            metadata=metadata,
        )

    async def publish_audio_frame(
        self,
        *,
        frame: AudioFrame,
        lane: OutputLane,
        output_id: str,
        turn_id: str | None,
        metadata: dict | None = None,
    ) -> OutputEvent | None:
        async with self._state_lock:
            record = self._outputs.get(output_id)
            if record is None or not record.active:
                return None
            if record.lane != lane or record.turn_id != turn_id:
                return None

        return await self._publish(
            kind=OutputKind.AUDIO_FRAME,
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            payload=frame,
            metadata=metadata,
        )

    async def publish_alignment(
        self,
        *,
        text: str,
        source_chunk_id: str,
        output_id: str,
        turn_id: str | None,
        lane: OutputLane,
        start_time_sec: float,
        end_time_sec: float,
        is_final: bool,
        partial: bool = False,
        timing_source: str = "synthesized_audio",
        metadata: dict | None = None,
    ) -> OutputEvent | None:
        if not source_chunk_id:
            raise ValueError("Alignment requires source_chunk_id")
        if start_time_sec < 0:
            raise ValueError("Alignment start_time_sec cannot be negative")
        if end_time_sec < start_time_sec:
            raise ValueError("Alignment end_time_sec cannot precede start_time_sec")

        async with self._state_lock:
            record = self._outputs.get(output_id)
            if record is None:
                return None

            self._validate_output(record, output_id=output_id, lane=lane, turn_id=turn_id)

        return await self._publish(
            kind=OutputKind.ALIGNMENT,
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputTextAudioAlignment(
                text=text,
                source_chunk_id=source_chunk_id,
                start_time_sec=start_time_sec,
                end_time_sec=end_time_sec,
                is_final=is_final,
                partial=partial,
                timing_source=timing_source,
            ),
            metadata=metadata,
        )

    async def publish_playback(
        self,
        *,
        output_id: str,
        lane: OutputLane,
        turn_id: str | None,
        playback_type: OutputPlaybackType,
        played_duration_sec: float,
        pushed_duration_sec: float,
        queued_duration_sec: float,
        metadata: dict | None = None,
    ) -> OutputEvent | None:
        if min(played_duration_sec, pushed_duration_sec, queued_duration_sec) < 0:
            raise ValueError("Playback durations cannot be negative")

        async with self._state_lock:
            record = self._outputs.get(output_id)
            if record is None:
                return None

            self._validate_output(record, output_id=output_id, lane=lane, turn_id=turn_id)

            if record.playback in {
                OutputPlaybackType.FINISHED,
                OutputPlaybackType.INTERRUPTED,
            }:
                return None

            if (
                playback_type
                in {
                    OutputPlaybackType.STARTED,
                    OutputPlaybackType.PROGRESS,
                }
                and record.terminal == OutputControlType.INTERRUPT
            ):
                return None

            if (
                playback_type == OutputPlaybackType.FINISHED
                and record.terminal != OutputControlType.COMPLETE
            ):
                return None

            if (
                playback_type == OutputPlaybackType.INTERRUPTED
                and record.terminal != OutputControlType.INTERRUPT
            ):
                return None

            record.playback = playback_type

        return await self._publish(
            kind=OutputKind.PLAYBACK,
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputPlayback(
                type=playback_type,
                played_duration_sec=played_duration_sec,
                pushed_duration_sec=pushed_duration_sec,
                queued_duration_sec=queued_duration_sec,
            ),
            metadata=metadata,
        )

    async def publish_transcript_chunk(
        self,
        *,
        text: str,
        output_id: str,
        turn_id: str | None,
        lane: OutputLane,
        chunk_id: str | None = None,
        source_chunk_id: str | None = None,
        start_time_sec: float | None = None,
        end_time_sec: float | None = None,
        is_first: bool = False,
        is_final: bool = False,
        interrupted: bool = False,
        metadata: dict | None = None,
    ) -> OutputEvent | None:
        if text == "" and not is_final:
            return None
        if start_time_sec is not None and start_time_sec < 0:
            raise ValueError("Transcript start_time_sec cannot be negative")
        if end_time_sec is not None and end_time_sec < 0:
            raise ValueError("Transcript end_time_sec cannot be negative")
        if (
            start_time_sec is not None
            and end_time_sec is not None
            and end_time_sec < start_time_sec
        ):
            raise ValueError("Transcript end_time_sec cannot precede start_time_sec")

        async with self._state_lock:
            record = self._outputs.get(output_id)
            if record is None:
                return None

            self._validate_output(record, output_id=output_id, lane=lane, turn_id=turn_id)

        return await self._publish(
            kind=OutputKind.TRANSCRIPT_CHUNK,
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputTranscriptChunk(
                text=text,
                chunk_id=chunk_id or uuid4().hex,
                source_chunk_id=source_chunk_id,
                start_time_sec=start_time_sec,
                end_time_sec=end_time_sec,
                is_first=is_first,
                is_final=is_final,
                interrupted=interrupted,
            ),
            metadata=metadata,
        )

    async def interrupt(
        self,
        *,
        lane: OutputLane | None = None,
        output_id: str | None = None,
        turn_id: str | None = None,
        reason: str,
        metadata: dict | None = None,
    ) -> OutputEvent:
        if lane is None and output_id is None and turn_id is None:
            raise ValueError("Output interrupt requires a target")

        async with self._state_lock:
            matching_outputs = {
                active_output_id: record
                for active_output_id, record in self._outputs.items()
                if record.interruptible
                and (lane is None or record.lane == lane)
                and (output_id is None or active_output_id == output_id)
                and (turn_id is None or record.turn_id == turn_id)
            }

            for record in matching_outputs.values():
                record.terminal = OutputControlType.INTERRUPT

        def _matches_event(event: OutputEvent) -> bool:
            # Only raw audio frames should be discarded globally. Semantic source
            # text, alignment and playback events are still required to calculate the
            # final delivered transcript after interruption.
            if event.kind != OutputKind.AUDIO_FRAME:
                return False
            if lane is not None and event.lane != lane:
                return False
            if output_id is not None and event.output_id != output_id:
                return False
            if turn_id is not None and event.turn_id != turn_id:
                return False
            return True

        await self.stream.discard_pending(_matches_event)

        inferred_lanes = {record.lane for record in matching_outputs.values()}
        effective_target_lane = lane
        if effective_target_lane is None and len(inferred_lanes) == 1:
            effective_target_lane = next(iter(inferred_lanes))

        return await self._publish(
            kind=OutputKind.CONTROL,
            lane=effective_target_lane or OutputLane.STATUS,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputControl(
                type=OutputControlType.INTERRUPT,
                reason=reason,
                target_lane=effective_target_lane,
                target_output_id=output_id,
                target_turn_id=turn_id,
            ),
            metadata={
                "interrupted_output_ids": tuple(matching_outputs),
                **dict(metadata or {}),
            },
        )

    async def complete(
        self,
        *,
        lane: OutputLane,
        output_id: str,
        turn_id: str | None = None,
        metadata: dict | None = None,
    ) -> OutputEvent | None:
        async with self._state_lock:
            record = self._outputs.get(output_id)
            if record is None or not record.active:
                return None
            if record.lane != lane or record.turn_id != turn_id:
                return None

            record.terminal = OutputControlType.COMPLETE

        return await self._publish(
            kind=OutputKind.CONTROL,
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputControl(
                type=OutputControlType.COMPLETE,
                reason="output_completed",
                target_lane=lane,
                target_output_id=output_id,
                target_turn_id=turn_id,
            ),
            metadata=metadata,
        )

    async def aclose(self) -> None:
        async with self._state_lock:
            if self._closed:
                return

            self._closed = True
            self._outputs.clear()

        await self.stream.aclose()
