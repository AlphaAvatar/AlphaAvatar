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
"""Session-scoped delivery, independently admitted records and execution observations."""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from uuid import uuid4

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env.output import EnvOutput
from alphaavatar.core.env.schemas.metadata import EMPTY_METADATA, OutputMetadata, freeze_metadata
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
    OutputCompletionBarrier,
    OutputControl,
    OutputEvent,
    OutputExecutionSignal,
    OutputIdentity,
    OutputJournalEvent,
    OutputPlayback,
    OutputRecordBatch,
    OutputScope,
    OutputSource,
    OutputStatusDecision,
    OutputTranscriptChunk,
)
from .schemas.validation import identifier
from .stream import OutputStream
from .timeline import OutputTimeline


def _idle() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


@dataclass(slots=True)
class _OutputRecord:
    identity: OutputIdentity
    source: OutputSource
    presentation: OutputStatusDecision | None
    text_mode: OutputTextMode
    terminal: OutputControlType | None = None
    terminal_reason: str | None = None
    playback: OutputPlaybackType | None = None
    text_sealed: bool = False
    text_completed: bool = False
    audio_completed: bool = False
    source_sealed: bool = False
    transcript_finalized: bool = False
    failed: bool = False
    last_audio_sequence: int = 0
    last_alignment_sequence: int = 0
    text_pending: int = 0
    media_pending: int = 0
    text_idle: asyncio.Event = field(default_factory=_idle)
    media_idle: asyncio.Event = field(default_factory=_idle)

    @property
    def active(self) -> bool:
        return self.terminal is None and not self.source_sealed and not self.failed

    @property
    def interruptible(self) -> bool:
        return self.terminal != OutputControlType.INTERRUPT and self.playback not in (
            OutputPlaybackType.FINISHED,
            OutputPlaybackType.INTERRUPTED,
        )


class OutputRuntime:
    """Own output admission and lifecycle; never Agent, provider or transport implementations.

    TEXT_COMPLETE seals text, AUDIO_COMPLETE seals synthesis and alignment, COMPLETE
    ends source production, and PLAYBACK reports local transport progress. Neither
    record admission nor source completion is a persistence or remote-delivery receipt.
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
        output_max_records: int = 4096,
        output_retired_records: int = 1024,
    ) -> None:
        identifier(session_id, "session_id")
        if any(
            type(value) is not int or value < 1
            for value in (output_max_records, output_retired_records)
        ):
            raise ValueError("Output record capacities must be positive integers")
        self._record_limit, self._retired_limit = output_max_records, output_retired_records
        self._retired: OrderedDict[str, tuple[OutputIdentity, str | None]] = OrderedDict()
        self.session_id, self.clock = session_id, clock or RuntimeClock()
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
        self._sequence_lock, self._state_lock, self._open_lock = (
            asyncio.Lock(),
            asyncio.Lock(),
            asyncio.Lock(),
        )
        self._outputs: dict[str, _OutputRecord] = {}
        self._closed = False
        self._publications: set[asyncio.Task[OutputEvent | None]] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._delivery_failure: Exception | None = None
        self._delivery_close_task: asyncio.Task[None] | None = None
        self._foreground_run: str | None = None
        self._foreground_turn: str | None = None
        self._status_scope: OutputScope | None = None
        self._status_revision = 0

    @staticmethod
    def _validate_identity(record: _OutputRecord, output: EnvOutput) -> None:
        identity = record.identity
        if (output.output_id, output.lane, output.scope) != (
            identity.output_id,
            identity.lane,
            identity.scope,
        ):
            raise ValueError("Output identity/ownership changed")

    @staticmethod
    def _validate_target(record: _OutputRecord, lane: OutputLane, turn_id: str | None) -> None:
        if (record.identity.lane, record.identity.scope.turn_id) != (lane, turn_id):
            raise ValueError("Output control identity mismatch")

    @staticmethod
    def _control(
        record: _OutputRecord, kind: OutputControlType, reason: str, metadata: OutputMetadata
    ) -> EnvOutput:
        identity = record.identity
        barrier = (
            OutputCompletionBarrier(record.last_audio_sequence, record.last_alignment_sequence)
            if kind in (OutputControlType.AUDIO_COMPLETE, OutputControlType.COMPLETE)
            else None
        )
        return EnvOutput(
            kind=OutputKind.CONTROL,
            lane=identity.lane,
            scope=identity.scope,
            output_id=identity.output_id,
            source=OutputSource("output.runtime"),
            payload=OutputControl(kind, reason, barrier=barrier),
            metadata=metadata,
        )

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("OutputRuntime is closed")

    def _check_delivery(self) -> None:
        self._check_open()
        if self._delivery_failure is not None:
            raise RuntimeError(
                "Output delivery is unavailable after a terminal publication failure"
            ) from self._delivery_failure

    def _accepts_owner(self, scope: OutputScope, presentation: OutputStatusDecision | None) -> bool:
        return (
            self.accepts_status(presentation)
            if presentation is not None
            else self.accepts_run(scope.run_id)
        )

    def _accepts_record(self, record: _OutputRecord) -> bool:
        return record.active and self._accepts_owner(record.identity.scope, record.presentation)

    def _delivery_guard(self, record: _OutputRecord) -> bool:
        # Sealing new intake must not discard content already admitted before its barrier.
        return (
            not record.failed
            and record.terminal != OutputControlType.INTERRUPT
            and self._accepts_owner(record.identity.scope, record.presentation)
        )

    async def _fail_delivery(self, failure: BaseException) -> None:
        # A partially delivered terminal fact cannot be retried safely or treated as a no-op.
        # Retire only realtime delivery: tools still own their record/execution cleanup.
        if self._delivery_failure is None:
            if isinstance(failure, Exception):
                self._delivery_failure = failure
            else:
                error = RuntimeError("Terminal output publication aborted")
                error.__cause__ = failure
                self._delivery_failure = error
            self._delivery_close_task = asyncio.create_task(
                self.stream.aclose(), name="output_delivery_failure_close"
            )
        if self._delivery_close_task is not None:
            await wait_for_cleanup(self._delivery_close_task)

    async def _dispatch(
        self,
        output: EnvOutput,
        *,
        guard: Callable[[], bool] | None = None,
        record: _OutputRecord | None = None,
    ) -> OutputEvent | None:
        try:
            if self._closed:
                return None
            self._check_delivery()
            async with self._sequence_lock:
                if self._closed:
                    return None
                self._check_delivery()
                if guard is not None and not guard():
                    return None
                now = self.clock.now()
                event = OutputEvent(
                    uuid4().hex,
                    self._sequence + 1,
                    self.session_id,
                    now.unix_seconds,
                    now.monotonic_ns,
                    output,
                )
                await self.timeline.append(event)
                self._sequence = event.sequence
                # A frame may reach one subscriber before another suspends in backpressure.
                # Its terminal barrier must still await a playback receipt after interruption.
                if record is not None:
                    if output.kind == OutputKind.AUDIO_FRAME:
                        record.last_audio_sequence = event.sequence
                    elif output.kind == OutputKind.ALIGNMENT:
                        record.last_alignment_sequence = event.sequence
            if guard is not None and not guard():
                return None
            try:
                await self.stream.publish(event, guard=guard)
            except RuntimeError:
                if not self._closed:
                    raise
                return None
            if not self._closed:
                self._check_delivery()
            return event if not self._closed and (guard is None or guard()) else None
        except BaseException as failure:
            terminal = (
                output.kind == OutputKind.CONTROL
                or (
                    isinstance(output.payload, OutputPlayback)
                    and output.payload.type
                    in (OutputPlaybackType.FINISHED, OutputPlaybackType.INTERRUPTED)
                )
                or (isinstance(output.payload, OutputTranscriptChunk) and output.payload.is_final)
            )
            if terminal and not self._closed:
                try:
                    await self._fail_delivery(failure)
                except BaseException as cleanup:
                    raise failure from cleanup
            raise

    async def _own_publication(
        self, operation: Coroutine[object, object, OutputEvent | None]
    ) -> OutputEvent | None:
        try:
            self._check_delivery()
        except BaseException:
            operation.close()
            raise
        # Register before suspension, including before a terminal task's first execution.
        task = asyncio.create_task(operation, name="output_terminal_publication")
        self._publications.add(task)
        task.add_done_callback(self._publications.discard)
        return await wait_for_cleanup(task)

    def activate_run(self, run_id: str) -> None:
        self._check_delivery()
        identifier(run_id, "run_id")
        self._foreground_run = run_id
        self._compact_outputs()

    def revoke_run(self, run_id: str) -> None:
        identifier(run_id, "run_id")
        if self._foreground_run == run_id:
            self._foreground_run = None

    def accepts_run(self, run_id: str | None) -> bool:
        return (
            not self._closed
            and self._delivery_failure is None
            and (run_id is None or run_id == self._foreground_run)
        )

    def update_status_scope(self, scope: OutputScope | None, revision: int) -> None:
        self._check_open()
        if scope is not None and type(scope) is not OutputScope:
            raise TypeError("Expected OutputScope or None")
        if type(revision) is not int or revision < self._status_revision:
            raise ValueError("Presentation revisions cannot move backwards")
        if revision == self._status_revision and scope != self._status_scope:
            raise ValueError("A presentation revision cannot identify two scopes")
        self._status_scope, self._status_revision = scope, revision

    def accepts_status(self, decision: OutputStatusDecision) -> bool:
        if type(decision) is not OutputStatusDecision:
            raise TypeError("Expected OutputStatusDecision")
        if (
            self._closed
            or self._delivery_failure is not None
            or self.clock.now().monotonic_ns > decision.expires_at_ns
        ):
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

    def _compact_outputs(self) -> None:
        # Never evict an in-flight terminal fact, or infer a playback receipt from generation.
        if self._publications:
            return
        for output_id, record in tuple(self._outputs.items()):
            if (
                record.terminal is None
                or record.text_pending
                or record.media_pending
                or self._accepts_owner(record.identity.scope, record.presentation)
            ):
                continue
            if record.text_mode == OutputTextMode.AUDIO_SYNCED and (
                not record.audio_completed or not record.transcript_finalized
            ):
                continue
            if record.last_audio_sequence and record.playback not in (
                OutputPlaybackType.FINISHED,
                OutputPlaybackType.INTERRUPTED,
            ):
                continue
            if record.last_alignment_sequence and not record.transcript_finalized:
                continue
            self._retired[output_id] = (record.identity, record.terminal_reason)
            self._outputs.pop(output_id)
        while len(self._retired) > self._retired_limit:
            self._retired.popitem(last=False)

    def terminal_reason(self, output_id: str) -> str | None:
        record = self._outputs.get(output_id)
        if record is not None:
            return record.terminal_reason
        terminal = self._retired.get(output_id)
        return terminal[1] if terminal is not None else None

    def output_identity(self, output_id: str) -> OutputIdentity | None:
        record = self._outputs.get(output_id)
        return record.identity if record is not None else None

    def can_deliver(self, output_id: str) -> bool:
        record = self._outputs.get(output_id)
        return record is not None and record.interruptible and self._delivery_guard(record)

    def is_active(self, output_id: str) -> bool:
        record = self._outputs.get(output_id)
        return record is not None and self._accepts_record(record)

    def text_mode(self, output_id: str) -> OutputTextMode | None:
        record = self._outputs.get(output_id)
        return record.text_mode if record is not None else None

    def transcript_finalized(self, output_id: str) -> bool:
        record = self._outputs.get(output_id)
        return record is not None and record.transcript_finalized

    def publish_records(self, batch: OutputRecordBatch) -> OutputJournalEvent[OutputRecordBatch]:
        self._check_open()
        if not isinstance(batch, OutputRecordBatch):
            raise TypeError("Expected OutputRecordBatch")
        # Retiring runs still own their real tool results; no foreground filtering here.
        return self.records.append(
            key=batch.batch_id,
            scope=batch.scope,
            payload=batch,
            digest=batch.digest,
            size_bytes=batch.size_bytes,
        )

    def publish_execution(
        self, signal: OutputExecutionSignal
    ) -> OutputJournalEvent[OutputExecutionSignal]:
        self._check_open()
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
        self._check_delivery()
        identifier(turn_id, "turn_id")
        self._foreground_turn = turn_id
        await self._interrupt(
            lane=OutputLane.TRANSIENT,
            output_id=None,
            turn_id=None,
            reason="new_turn_started",
            metadata=EMPTY_METADATA,
            affects_scope=False,
        )

    async def _prepare_text(self, output: EnvOutput) -> _OutputRecord | None:
        async with self._open_lock:
            self._check_delivery()
            if output.output_id in self._retired:
                return None
            existing = self._outputs.get(output.output_id)
            if existing is not None:
                self._validate_identity(existing, output)
                if existing.source != output.source or existing.presentation != output.presentation:
                    raise ValueError("Source text provenance changed")
                return existing if self._accepts_record(existing) else None
            if not self._accepts_owner(output.scope, output.presentation):
                return None
            if output.payload.replace_lane:
                await self._interrupt(
                    lane=output.lane,
                    output_id=None,
                    turn_id=None,
                    reason="replaced_by_new_text_output",
                    metadata=EMPTY_METADATA,
                    affects_scope=False,
                )
            if output.lane == OutputLane.ASSISTANT:
                await self._interrupt(
                    lane=OutputLane.TRANSIENT,
                    output_id=None,
                    turn_id=None,
                    reason="assistant_output_started",
                    metadata=EMPTY_METADATA,
                    affects_scope=False,
                )
            if not self._accepts_owner(output.scope, output.presentation):
                return None
            if len(self._outputs) >= self._record_limit:
                self._compact_outputs()
                if len(self._outputs) >= self._record_limit:
                    raise RuntimeError("Output state capacity exhausted before settlement")
            record = _OutputRecord(
                OutputIdentity(output.output_id, output.lane, output.scope),
                output.source,
                output.presentation,
                output.payload.mode,
            )
            self._outputs[output.output_id] = record
            return record

    async def publish(self, output: EnvOutput) -> OutputEvent | None:
        """Admit a validated content object; control facts cannot be supplied by producers."""
        if type(output) is not EnvOutput:
            raise TypeError("Expected EnvOutput")
        if output.kind == OutputKind.CONTROL:
            raise ValueError("Control facts belong to OutputRuntime control operations")

        self._check_delivery()
        if output.kind == OutputKind.STATUS:
            return await self._dispatch(output, guard=lambda: self.accepts_status(output.payload))
        if output.kind == OutputKind.TEXT_CHUNK:
            record = await self._prepare_text(output)
            return None if record is None else await self._content(output, record)

        record = self._outputs.get(output.output_id)
        if record is None:
            return None

        self._validate_identity(record, output)
        if output.kind in (OutputKind.AUDIO_FRAME, OutputKind.ALIGNMENT):
            return await self._content(output, record)

        terminal = (
            isinstance(output.payload, OutputPlayback)
            and output.payload.type in (OutputPlaybackType.FINISHED, OutputPlaybackType.INTERRUPTED)
        ) or (isinstance(output.payload, OutputTranscriptChunk) and output.payload.is_final)
        operation = self._feedback(output, record)
        return await self._own_publication(operation) if terminal else await operation

    async def _content(self, output: EnvOutput, record: _OutputRecord) -> OutputEvent | None:
        text = output.kind == OutputKind.TEXT_CHUNK
        alignment = output.kind == OutputKind.ALIGNMENT
        async with self._state_lock:
            self._validate_identity(record, output)
            # Alignments report already-synthesized phrases, not new generation authority.
            # Preserve exact old-output facts until synthesis seals them, including interruption.
            if self._closed or (not alignment and not self._accepts_record(record)):
                return None
            if text:
                if record.text_sealed:
                    return None
                if output.payload.mode != record.text_mode:
                    raise ValueError("Output text mode cannot change")
                record.text_sealed = output.payload.is_final
                record.text_pending += 1
                record.text_idle.clear()
            else:
                if record.audio_completed:
                    return None
                record.media_pending += 1
                record.media_idle.clear()
        failure: BaseException | None = None
        try:
            return await self._dispatch(
                output,
                record=record,
                guard=None if alignment else lambda: self._delivery_guard(record),
            )
        except BaseException as exc:
            record.failed = True
            failure = exc
            raise
        finally:
            if text:
                record.text_pending -= 1
                if record.text_pending == 0:
                    record.text_idle.set()
            else:
                record.media_pending -= 1
                if record.media_pending == 0:
                    record.media_idle.set()
            if failure is not None and not self._closed and self._delivery_failure is None:
                try:
                    await self.interrupt(
                        output_id=record.identity.output_id, reason="content_publication_failed"
                    )
                except BaseException as cleanup:
                    raise failure from cleanup

    async def _feedback(self, output: EnvOutput, record: _OutputRecord) -> OutputEvent | None:
        async with self._state_lock:
            self._check_delivery()
            self._validate_identity(record, output)
            payload = output.payload
            if isinstance(payload, OutputPlayback):
                if record.playback in (OutputPlaybackType.FINISHED, OutputPlaybackType.INTERRUPTED):
                    return None
                if payload.type in (OutputPlaybackType.STARTED, OutputPlaybackType.PROGRESS):
                    if not self.can_deliver(record.identity.output_id):
                        return None
                elif payload.type == OutputPlaybackType.FINISHED:
                    if record.terminal != OutputControlType.COMPLETE:
                        return None
                elif payload.type == OutputPlaybackType.INTERRUPTED:
                    if record.terminal != OutputControlType.INTERRUPT:
                        return None
                record.playback = payload.type
            elif isinstance(payload, OutputTranscriptChunk):
                if record.transcript_finalized:
                    return None
                if payload.is_final:
                    # Priority interruption may precede consumer state or this final's admission.
                    # Reconcile the exact output's fact without mutating the submitted object.
                    if record.terminal == OutputControlType.INTERRUPT and not payload.interrupted:
                        output = replace(output, payload=replace(payload, interrupted=True))
                    record.transcript_finalized = True
            else:
                raise TypeError("Unsupported output feedback")
        return await self._dispatch(output)

    async def finish_text(
        self,
        *,
        output_id: str,
        turn_id: str,
        run_id: str,
        lane: OutputLane = OutputLane.ASSISTANT,
        metadata: Mapping[str, object] | None = None,
    ) -> OutputEvent | None:
        identifier(output_id, "output_id")
        identifier(turn_id, "turn_id")
        identifier(run_id, "run_id")
        if type(lane) is not OutputLane:
            raise TypeError("Expected OutputLane")
        fields = freeze_metadata(metadata)

        async def finish() -> OutputEvent | None:
            async with self._state_lock:
                if self._closed:
                    return None
                self._check_delivery()
                record = self._outputs.get(output_id)
                if record is None:
                    return None
                self._validate_target(record, lane, turn_id)
                if record.identity.scope.run_id != run_id:
                    raise ValueError("Text completion run mismatch")
                if record.text_completed or not self._accepts_record(record):
                    return None
                record.text_sealed = record.text_completed = True
            await record.text_idle.wait()
            return await self._dispatch(
                self._control(
                    record, OutputControlType.TEXT_COMPLETE, "source_text_completed", fields
                )
            )

        return await self._own_publication(finish())

    async def finish_audio(
        self,
        *,
        output_id: str,
        lane: OutputLane,
        turn_id: str | None,
        reason: str = "synthesis_completed",
    ) -> OutputEvent | None:
        identifier(output_id, "output_id")
        identifier(reason, "reason")
        identifier(turn_id, "turn_id", optional=True)
        if type(lane) is not OutputLane:
            raise TypeError("Expected OutputLane")

        async def finish() -> OutputEvent | None:
            async with self._state_lock:
                if self._closed:
                    return None
                self._check_delivery()
                record = self._outputs.get(output_id)
                if record is None:
                    return None
                self._validate_target(record, lane, turn_id)
                if record.audio_completed:
                    return None
                record.audio_completed = True
            # An admitted frame/alignment may still be in a reliable subscriber's backpressure.
            await record.media_idle.wait()
            return await self._dispatch(
                self._control(record, OutputControlType.AUDIO_COMPLETE, reason, EMPTY_METADATA)
            )

        return await self._own_publication(finish())

    async def complete(
        self,
        *,
        lane: OutputLane,
        output_id: str,
        turn_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> OutputEvent | None:
        identifier(output_id, "output_id")
        identifier(turn_id, "turn_id", optional=True)
        if type(lane) is not OutputLane:
            raise TypeError("Expected OutputLane")
        fields = freeze_metadata(metadata)

        async def finish() -> OutputEvent | None:
            async with self._state_lock:
                if self._closed:
                    return None
                self._check_delivery()
                record = self._outputs.get(output_id)
                if record is None:
                    return None
                self._validate_target(record, lane, turn_id)
                if not record.active:
                    return None
                record.source_sealed = True
            await record.text_idle.wait()
            await record.media_idle.wait()
            async with self._state_lock:
                if record.terminal is not None or record.failed:
                    return None
                record.terminal = OutputControlType.COMPLETE
                record.terminal_reason = "output_completed"
            return await self._dispatch(
                self._control(record, OutputControlType.COMPLETE, "output_completed", fields)
            )

        return await self._own_publication(finish())

    async def interrupt(
        self,
        *,
        lane: OutputLane | None = None,
        output_id: str | None = None,
        turn_id: str | None = None,
        reason: str,
        metadata: Mapping[str, object] | None = None,
    ) -> OutputEvent | None:
        if lane is None and output_id is None and turn_id is None:
            raise ValueError("Output interrupt requires a target")
        if lane is not None and type(lane) is not OutputLane:
            raise TypeError("Expected OutputLane")

        identifier(output_id, "output_id", optional=True)
        identifier(turn_id, "turn_id", optional=True)
        identifier(reason, "reason")
        fields = freeze_metadata(metadata)
        return await self._interrupt(
            lane=lane,
            output_id=output_id,
            turn_id=turn_id,
            reason=reason,
            metadata=fields,
            affects_scope=output_id is None and lane != OutputLane.TRANSIENT,
        )

    async def _interrupt(
        self,
        *,
        lane: OutputLane | None,
        output_id: str | None,
        turn_id: str | None,
        reason: str,
        metadata: OutputMetadata,
        affects_scope: bool,
    ) -> OutputEvent | None:
        async with self._state_lock:
            self._check_delivery()
            matching = tuple(
                record
                for identity, record in self._outputs.items()
                if record.interruptible
                and (lane is None or record.identity.lane == lane)
                and (output_id is None or identity == output_id)
                and (turn_id is None or record.identity.scope.turn_id == turn_id)
            )
            targets = tuple(record.identity for record in matching)
            for record in matching:
                record.terminal = OutputControlType.INTERRUPT
                record.terminal_reason = reason
        if not targets:
            return None

        ids = frozenset(target.output_id for target in targets)
        lanes = {target.lane for target in targets}
        output = EnvOutput(
            kind=OutputKind.CONTROL,
            lane=next(iter(lanes)) if len(lanes) == 1 else OutputLane.STATUS,
            scope=None,
            source=OutputSource("output.runtime"),
            payload=OutputControl(
                OutputControlType.INTERRUPT, reason, targets, affects_scope=affects_scope
            ),
            metadata=metadata,
        )

        async def publish() -> OutputEvent | None:
            try:
                await self.stream.discard_pending(
                    lambda event: event.output.kind == OutputKind.AUDIO_FRAME
                    and event.output.output_id in ids
                )
            except BaseException as failure:
                if not self._closed:
                    try:
                        await self._fail_delivery(failure)
                    except BaseException as cleanup:
                        raise failure from cleanup
                raise
            return await self._dispatch(output)

        return await self._own_publication(publish())

    async def _close(self) -> None:
        async with self._state_lock:
            self._closed = True
            self._foreground_run = None
            self._status_scope = None
            self.records.close()
            self.execution.close()
            publications = tuple(self._publications)
        errors: list[Exception] = []
        try:
            # Release subscribers before joining owned publishers or source-drain barriers.
            await self.stream.aclose()
            if self._delivery_close_task is not None:
                await wait_for_cleanup(self._delivery_close_task)
        except asyncio.CancelledError as exc:
            error = RuntimeError("Output stream cleanup cancelled itself")
            error.__cause__ = exc
            errors.append(error)
        except Exception as exc:
            errors.append(exc)
        if errors:
            for publication in publications:
                publication.cancel()
        results = await asyncio.gather(*publications, return_exceptions=True)
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                error = RuntimeError("Owned output publication cancelled itself")
                error.__cause__ = result
                errors.append(error)
            elif isinstance(result, Exception):
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result
        self._outputs.clear()
        self._retired.clear()
        self._publications.clear()

        # Completed publication tasks have left the in-flight set; retain their first failure.
        if self._delivery_failure is not None and all(
            error is not self._delivery_failure for error in errors
        ):
            errors.append(self._delivery_failure)
        if errors:
            raise ExceptionGroup("Output publication shutdown failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="output_runtime_close")
        await wait_for_cleanup(self._close_task)
