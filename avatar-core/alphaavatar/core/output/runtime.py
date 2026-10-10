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
"""Session-scoped output: delivery, retained model records and execution observations."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from hashlib import sha256
from uuid import uuid4

from alphaavatar.core.media import AudioFrame
from alphaavatar.core.time import RuntimeClock

from .enums import (
    OutputAudience,
    OutputControlType,
    OutputKind,
    OutputLane,
    OutputPlaybackType,
    OutputTextMode,
)
from .journal import OutputJournal
from .schemas import (
    OutputControl,
    OutputEvent,
    OutputExecutionSignal,
    OutputJournalEvent,
    OutputPlayback,
    OutputRecordBatch,
    OutputScope,
    OutputStatusDecision,
    OutputTextAudioAlignment,
    OutputTextChunk,
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
    text_completed: bool = False
    run_id: str | None = None
    status_decision: OutputStatusDecision | None = None

    @property
    def active(self) -> bool:
        return self.terminal is None

    @property
    def interruptible(self) -> bool:
        return self.terminal != OutputControlType.INTERRUPT and self.playback not in {
            OutputPlaybackType.FINISHED,
            OutputPlaybackType.INTERRUPTED,
        }


class OutputRuntime:
    """Own independent delivery and semantic streams, never Agent or plugin implementations.

    records is a lossless-admission journal, not a durable database. execution is a
    bounded observation journal with explicit gaps. Neither is forwarded to RTC.
    TEXT_COMPLETE ends model text; COMPLETE ends all text/audio production.
    """

    def __init__(
        self,
        *,
        session_id: str,
        clock: RuntimeClock | None = None,
        timeline_max_items: int = 4096,
        record_max_batches: int = 1024,
        record_max_bytes: int = 67_108_864,
        execution_max_events: int = 2048,
    ) -> None:
        if not session_id:
            raise ValueError("OutputRuntime requires a non-empty session_id")

        self.session_id = session_id
        self.clock = clock or RuntimeClock()

        self.stream = OutputStream()
        self.timeline = OutputTimeline(max_items=timeline_max_items)

        self.records: OutputJournal[OutputRecordBatch] = OutputJournal(
            session_id=session_id,
            clock=self.clock,
            max_items=record_max_batches,
            max_bytes=record_max_bytes,
            lossless=True,
        )
        self.execution: OutputJournal[OutputExecutionSignal] = OutputJournal(
            session_id=session_id,
            clock=self.clock,
            max_items=execution_max_events,
            max_bytes=8_388_608,
            lossless=False,
        )

        self._sequence = 0
        self._sequence_lock = asyncio.Lock()
        self._outputs: dict[str, _OutputRecord] = {}
        self._state_lock = asyncio.Lock()
        self._open_lock = asyncio.Lock()
        self._closed = False

        # A lease, not a cache of every retired run. None means no native foreground owner.
        self._foreground_run: str | None = None
        self._foreground_turn: str | None = None
        self._status_scope: OutputScope | None = None
        self._status_revision = 0

    @staticmethod
    def _validate_output(
        record: _OutputRecord,
        *,
        output_id: str,
        lane: OutputLane,
        turn_id: str | None,
    ) -> None:
        if record.lane != lane:
            raise ValueError(f"Output lane mismatch output_id={output_id!r}")
        if record.turn_id != turn_id:
            raise ValueError(f"Output turn mismatch output_id={output_id!r}")

    def _accepts_owner(self, run_id: str | None, decision: OutputStatusDecision | None) -> bool:
        return self.accepts_status(decision) if decision is not None else self.accepts_run(run_id)

    def _accepts_record(self, record: _OutputRecord) -> bool:
        return record.active and self._accepts_owner(record.run_id, record.status_decision)

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
        run_id: str | None = None,
        status_decision: OutputStatusDecision | None = None,
    ) -> tuple[_OutputRecord | None, bool]:
        async with self._state_lock:
            if self._closed:
                raise RuntimeError("OutputRuntime is closed")
            if not self._accepts_owner(run_id, status_decision):
                return None, False
            record = self._outputs.get(output_id)
            if record is not None:
                self._validate_output(record, output_id=output_id, lane=lane, turn_id=turn_id)
                if record.run_id != run_id or record.status_decision != status_decision:
                    raise ValueError("Output execution owner mismatch")
                return (record if record.active else None), False
            record = _OutputRecord(
                lane, turn_id, origin_kind, run_id=run_id, status_decision=status_decision
            )
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
        run_id: str | None = None,
        status_decision: OutputStatusDecision | None = None,
    ) -> tuple[_OutputRecord | None, bool]:
        async with self._open_lock:
            if not self._accepts_owner(run_id, status_decision):
                return None, False
            existing = await self._get_output(output_id)
            if not self._accepts_owner(run_id, status_decision):
                return None, False
            if existing is not None:
                self._validate_output(existing, output_id=output_id, lane=lane, turn_id=turn_id)
                if existing.run_id != run_id or existing.status_decision != status_decision:
                    raise ValueError("Output execution owner mismatch")
                return (existing if existing.active else None), False
            if replace_lane:
                await self.interrupt(
                    lane=lane,
                    reason=replace_reason,
                    metadata={"replacement_output_id": output_id, "replacement_turn_id": turn_id},
                )
            if not self._accepts_owner(run_id, status_decision):
                return None, False
            if preempt_transient and lane != OutputLane.TRANSIENT:
                await self.interrupt(
                    lane=OutputLane.TRANSIENT,
                    reason="assistant_output_started",
                    metadata={"assistant_output_id": output_id, "turn_id": turn_id},
                )
            return await self._get_or_create_output(
                output_id=output_id,
                lane=lane,
                turn_id=turn_id,
                origin_kind=origin_kind,
                run_id=run_id,
                status_decision=status_decision,
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
        guard: Callable[[], bool] | None = None,
    ) -> OutputEvent | None:
        if self._closed:
            raise RuntimeError("OutputRuntime is closed")

        async with self._sequence_lock:
            if self._closed:
                raise RuntimeError("OutputRuntime is closed")
            if guard is not None and not guard():
                return None

            self._sequence += 1
            now = self.clock.now()
            event = OutputEvent(
                event_id=uuid4().hex,
                sequence=self._sequence,
                session_id=self.session_id,
                created_at=now.unix_seconds,
                monotonic_ns=now.monotonic_ns,
                kind=kind,
                lane=lane,
                output_id=output_id,
                turn_id=turn_id,
                payload=payload,
                metadata=dict(metadata or {}),
            )
            await self.timeline.append(event)
        if guard is not None and not guard():
            return None
        await self.stream.publish(event, guard=guard)
        return event if guard is None or guard() else None

    def activate_run(self, run_id: str) -> None:
        if self._closed or not isinstance(run_id, str) or not run_id:
            raise RuntimeError("Cannot activate this output run")
        self._foreground_run = run_id

    def revoke_run(self, run_id: str) -> None:
        if self._foreground_run == run_id:
            self._foreground_run = None

    def accepts_run(self, run_id: str | None) -> bool:
        return not self._closed and (run_id is None or run_id == self._foreground_run)

    def update_status_scope(self, scope: OutputScope | None, revision: int) -> None:
        """Advance the consumer-owned presentation view without granting model output rights."""
        if self._closed:
            raise RuntimeError("OutputRuntime is closed")
        if scope is not None and not isinstance(scope, OutputScope):
            raise TypeError("Expected OutputScope or None")
        if type(revision) is not int or revision < self._status_revision:
            raise ValueError("Presentation revisions cannot move backwards")
        if revision == self._status_revision and scope != self._status_scope:
            raise ValueError("A presentation revision cannot identify two scopes")
        self._status_scope, self._status_revision = scope, revision

    def accepts_status(self, decision: OutputStatusDecision) -> bool:
        if self._closed or self.clock.now().monotonic_ns > decision.expires_at_ns:
            return False
        if decision.audience == OutputAudience.SYSTEM:
            return True
        return (
            decision.scope == self._status_scope
            and decision.revision == self._status_revision
            and (self._foreground_turn is None or decision.scope.turn_id == self._foreground_turn)
            and (
                decision.scope.run_id == self._foreground_run
                or (decision.terminal and self._foreground_run is None)
            )
        )

    def is_active(self, output_id: str) -> bool:
        record = self._outputs.get(output_id)
        return record is not None and self._accepts_record(record)

    def publish_records(self, batch: OutputRecordBatch) -> OutputJournalEvent[OutputRecordBatch]:
        if self._closed:
            raise RuntimeError("OutputRuntime is closed")
        if not isinstance(batch, OutputRecordBatch):
            raise TypeError("Expected OutputRecordBatch")

        # Deliberately no foreground filter: retiring runs must retain their tool facts.
        return self.records.append(
            key=batch.batch_id,
            scope=batch.scope,
            payload=batch,
            digest=batch.digest,
            size_bytes=batch.size_bytes,
        )

    def publish_execution(self, signal: OutputExecutionSignal) -> OutputJournalEvent:
        if self._closed:
            raise RuntimeError("OutputRuntime is closed")
        if not isinstance(signal, OutputExecutionSignal):
            raise TypeError("Expected OutputExecutionSignal")
        raw = json.dumps(asdict(signal), ensure_ascii=False, sort_keys=True).encode()

        return self.execution.append(
            key=uuid4().hex,
            scope=signal.scope,
            payload=signal,
            digest=sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )

    async def start_turn(self, *, turn_id: str) -> None:
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("Turn identity is required")
        self._foreground_turn = turn_id
        await self.interrupt(
            lane=OutputLane.TRANSIENT,
            reason="new_turn_started",
            metadata={"new_turn_id": turn_id},
        )

    async def publish_status(self, *, decision: OutputStatusDecision) -> OutputEvent | None:
        if not isinstance(decision, OutputStatusDecision):
            raise TypeError("Status output requires a presentation decision")

        def valid() -> bool:
            return self.accepts_status(decision)

        return await self._publish(
            kind=OutputKind.STATUS,
            lane=OutputLane.STATUS,
            output_id=None,
            turn_id=decision.scope.turn_id,
            payload=decision,
            metadata={"origin": "status.presentation", "decision_id": decision.decision_id},
            guard=valid,
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
        run_id: str | None = None,
        status_decision: OutputStatusDecision | None = None,
    ) -> OutputEvent | None:
        if status_decision is not None:
            if not isinstance(status_decision, OutputStatusDecision):
                raise TypeError("Expected OutputStatusDecision")
            if (
                lane != OutputLane.TRANSIENT
                or status_decision.audience != OutputAudience.USER
                or not status_decision.narration_key
                or turn_id != status_decision.scope.turn_id
                or run_id != status_decision.scope.run_id
            ):
                raise ValueError("Status narration requires its own transient presentation scope")
        if text == "" or not self._accepts_owner(run_id, status_decision):
            return None

        record, _ = await self._prepare_output(
            output_id=output_id,
            lane=lane,
            turn_id=turn_id,
            origin_kind=OutputKind.TEXT_CHUNK,
            replace_lane=replace_lane,
            replace_reason="replaced_by_new_text_output",
            preempt_transient=lane == OutputLane.ASSISTANT,
            run_id=run_id,
            status_decision=status_decision,
        )
        if record is None:
            return None

        async with self._state_lock:
            if not self._accepts_record(record) or record.text_completed:
                return None

            first_chunk = not record.text_started
            record.text_started = True

        return await self._publish(
            kind=OutputKind.TEXT_CHUNK,
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputTextChunk(text, chunk_id or uuid4().hex, first_chunk, is_final, mode),
            metadata={**dict(metadata or {}), **({"run_id": run_id} if run_id else {})},
            guard=lambda: self._accepts_record(record),
        )

    async def finish_text(
        self,
        *,
        output_id: str,
        turn_id: str,
        lane: OutputLane = OutputLane.ASSISTANT,
        run_id: str,
        metadata: dict | None = None,
    ) -> OutputEvent | None:
        async with self._state_lock:
            record = self._outputs.get(output_id)
            if record is None or not record.active or record.text_completed:
                return None
            self._validate_output(record, output_id=output_id, lane=lane, turn_id=turn_id)
            if record.run_id != run_id or not self._accepts_record(record):
                return None
            record.text_completed = True
        return await self._publish(
            kind=OutputKind.CONTROL,
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputControl(
                OutputControlType.TEXT_COMPLETE,
                "source_text_completed",
                lane,
                output_id,
                turn_id,
            ),
            metadata={**dict(metadata or {}), "run_id": run_id},
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
            if record is None or not self._accepts_record(record):
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
            guard=lambda: self._accepts_record(record),
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
        if start_time_sec < 0 or end_time_sec < start_time_sec:
            raise ValueError("Invalid alignment time range")
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
                text,
                source_chunk_id,
                start_time_sec,
                end_time_sec,
                is_final,
                partial,
                timing_source,
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
            if record.playback in {OutputPlaybackType.FINISHED, OutputPlaybackType.INTERRUPTED}:
                return None
            if playback_type in {OutputPlaybackType.STARTED, OutputPlaybackType.PROGRESS}:
                if record.terminal == OutputControlType.INTERRUPT:
                    return None
            if playback_type == OutputPlaybackType.FINISHED:
                if record.terminal != OutputControlType.COMPLETE:
                    return None
            if playback_type == OutputPlaybackType.INTERRUPTED:
                if record.terminal != OutputControlType.INTERRUPT:
                    return None
            record.playback = playback_type
        return await self._publish(
            kind=OutputKind.PLAYBACK,
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputPlayback(
                playback_type,
                played_duration_sec,
                pushed_duration_sec,
                queued_duration_sec,
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
                text,
                chunk_id or uuid4().hex,
                source_chunk_id,
                start_time_sec,
                end_time_sec,
                is_first,
                is_final,
                interrupted,
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
                identity: record
                for identity, record in self._outputs.items()
                if record.interruptible
                and (lane is None or record.lane == lane)
                and (output_id is None or identity == output_id)
                and (turn_id is None or record.turn_id == turn_id)
            }
            for record in matching_outputs.values():
                record.terminal = OutputControlType.INTERRUPT

        def matches(event: OutputEvent) -> bool:
            # Keep semantic text/alignment/playback required for final interrupted transcripts.
            return (
                event.kind == OutputKind.AUDIO_FRAME
                and (lane is None or event.lane == lane)
                and (output_id is None or event.output_id == output_id)
                and (turn_id is None or event.turn_id == turn_id)
            )

        await self.stream.discard_pending(matches)
        inferred_lanes = {record.lane for record in matching_outputs.values()}
        target_lane = lane
        if target_lane is None and len(inferred_lanes) == 1:
            target_lane = next(iter(inferred_lanes))

        return await self._publish(
            kind=OutputKind.CONTROL,
            lane=target_lane or OutputLane.STATUS,
            output_id=output_id,
            turn_id=turn_id,
            payload=OutputControl(
                OutputControlType.INTERRUPT,
                reason,
                target_lane,
                output_id,
                turn_id,
            ),
            metadata={"interrupted_output_ids": tuple(matching_outputs), **dict(metadata or {})},
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
                OutputControlType.COMPLETE,
                "output_completed",
                lane,
                output_id,
                turn_id,
            ),
            metadata=metadata,
        )

    async def aclose(self) -> None:
        async with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._foreground_run = None
            self._status_scope = None
            self._outputs.clear()
            self.records.close()
            self.execution.close()
        await self.stream.aclose()
