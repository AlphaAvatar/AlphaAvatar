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
import time
from collections import OrderedDict
from functools import partial
from typing import TYPE_CHECKING

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.lifecycle import LifecycleComponent
from alphaavatar.core.log.events import log_event
from alphaavatar.core.output.enums import OutputControlType, OutputKind, OutputPlaybackType
from alphaavatar.core.output.schemas import (
    OutputControl,
    OutputPlayback,
    OutputStatusDecision,
    OutputTextAudioAlignment,
    OutputTextChunk,
    OutputTranscriptChunk,
)

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime

logger = logging.getLogger(__name__)
_MEDIA = frozenset(
    (
        ObservationKind.AUDIO_FRAME,
        ObservationKind.SPEECH_FRAME,
        ObservationKind.VIDEO_FRAME,
        ObservationKind.SCREEN_FRAME,
        ObservationKind.TRANSCRIPT_DELTA,
    )
)


class CoreEventTrace(LifecycleComponent):
    """Optional metadata-only observer; never a required consumer or an execution owner."""

    PREFIX = "host.log.timeline"

    def __init__(self, runtime: AvatarRuntime) -> None:
        self._runtime = runtime
        self._tasks: list[asyncio.Task] = []
        self._journals: list[tuple[object, str]] = []
        self._sampled: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._subscription = None
        self._start_task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None

    def _log(self, stream: str, *, gap: bool = False, **fields) -> None:
        log_event(
            logger,
            "core.gap" if gap else "core.event",
            level=logging.WARNING if gap else logging.DEBUG,
            session_id=self._runtime.session.session_id,
            stream=stream,
            observed_time_ns=time.monotonic_ns(),
            **fields,
        )

    def _sample(self, kind: str, output_id: str, now: int, *, interval: int = 0) -> bool:
        key = kind, output_id
        previous = self._sampled.get(key)
        if previous is not None and (not interval or now - previous < interval):
            return False
        self._sampled[key] = now
        self._sampled.move_to_end(key)
        while len(self._sampled) > 1024:
            self._sampled.popitem(last=False)
        return True

    def _perception_event(self, event) -> None:
        fields = {
            "event_id": event.event_id,
            "sequence": event.sequence,
            "event_time_ns": event.time_range.end.monotonic_ns,
        }
        if (source := event.source_state) is not None:
            fields.update(
                event_kind="source_state",
                source_id=source.source_id,
                source_generation=source.source_generation,
                state=source.state.value,
                modality=source.modality.value,
                source_kind=source.source_kind.value,
            )
        elif (observation := event.observation) is not None:
            if observation.kind in _MEDIA:
                return
            fields.update(
                event_kind=observation.kind.value, observation_id=observation.observation_id
            )
        elif (annotation := event.annotation) is not None:
            fields.update(
                event_kind=annotation.kind.value,
                annotation_id=annotation.annotation_id,
                observation_id=annotation.observation_id,
                producer=annotation.source,
            )
        self._log("perception", **fields)

    async def _perception(self) -> None:
        stream, consumer = self._runtime.perception.events, f"{self.PREFIX}.perception"
        while True:
            await stream.wait_for_pending(consumer_id=consumer)
            batch = stream.read_pending(consumer_id=consumer, limit=64)
            if batch.has_gap:
                self._log(
                    "perception", gap=True, missed_count=batch.missed_count, reason="retention_gap"
                )
            for event in batch.items:
                self._perception_event(event)
            stream.commit(consumer_id=consumer, cursor_seq=batch.cursor_seq)
            # Diagnostic observation is batched; no task or log per incoming PCM frame.
            await asyncio.sleep(0.05)

    async def _turns(self) -> None:
        stream, consumer = self._runtime.turn.events, f"{self.PREFIX}.turn"
        while True:
            await stream.wait_for_pending(consumer_id=consumer)
            batch = stream.read_pending(consumer_id=consumer, limit=32)
            if batch.has_gap:
                self._log("turn", gap=True, missed_count=batch.missed_count, reason="retention_gap")
            for event in batch.items:
                value = event.snapshot
                self._log(
                    "turn",
                    event_id=event.event_id,
                    sequence=event.sequence,
                    event_time_ns=value.committed_at.monotonic_ns,
                    event_kind="committed",
                    turn_id=value.turn_id,
                    input_id=value.input_id,
                    modality=value.modality.value,
                    cutoff_sequence=value.cutoff.sequence,
                    context_id=value.context_ids[0] if value.context_ids else None,
                )
            stream.commit(consumer_id=consumer, cursor_seq=batch.cursor_seq)
            await asyncio.sleep(0)

    async def _journal(self, stream, name: str, consumer: str) -> None:
        while await stream.wait_for_pending(consumer_id=consumer):
            batch = stream.read_pending(consumer_id=consumer, limit=32)
            if batch.has_gap:
                self._log(name, gap=True, missed_count=batch.missed_count, reason="retention_gap")
            for event in batch.items:
                value, scope = event.payload, event.scope
                fields = {
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                    "event_time_ns": event.monotonic_ns,
                    "context_id": scope.context_id,
                    "turn_id": scope.turn_id,
                    "run_id": scope.run_id,
                }
                if name == "output.execution":
                    fields.update(
                        event_kind=value.kind.value,
                        state=value.state,
                        request_id=value.request_id,
                        call_id=value.call_id,
                        outcome=value.outcome,
                        executed=value.executed,
                    )
                else:
                    fields.update(
                        event_kind="record_batch",
                        batch_id=value.batch_id,
                        schema=value.schema,
                        producer=value.source,
                        item_count=len(value.items),
                    )
                self._log(name, **fields)
            stream.commit(consumer_id=consumer, cursor_seq=batch.cursor_seq)
            await asyncio.sleep(0)

    def _output_event(self, event) -> None:
        output, value = event.output, event.output.payload
        fields = {
            "event_id": event.event_id,
            "sequence": event.sequence,
            "event_time_ns": event.monotonic_ns,
            "event_kind": output.kind.value,
            "context_id": output.scope.context_id if output.scope else None,
            "turn_id": output.scope.turn_id if output.scope else None,
            "run_id": output.scope.run_id if output.scope else None,
            "output_id": output.output_id,
            "producer": output.source.producer,
            "request_id": output.source.request_id,
            "item_id": output.source.item_id,
            "lane": output.lane.value,
        }
        if isinstance(value, OutputTextChunk):
            if not self._sample("text", output.output_id or "", event.monotonic_ns):
                return
            fields.update(
                event_kind="first_text_chunk", chunk_id=value.chunk_id, text_chars=len(value.text)
            )
        elif isinstance(value, OutputPlayback):
            if value.type == OutputPlaybackType.PROGRESS and not self._sample(
                "playback", output.output_id or "", event.monotonic_ns, interval=250_000_000
            ):
                return
            fields.update(
                playback_type=value.type.value,
                played_seconds=value.played_duration_sec,
                pushed_seconds=value.pushed_duration_sec,
                queued_seconds=value.queued_duration_sec,
                measurement=output.metadata.get("measurement"),
            )
        elif isinstance(value, OutputTextAudioAlignment):
            fields.update(
                alignment_id=value.alignment_id,
                source_chunk_id=value.source_chunk_ids[0]
                if len(value.source_chunk_ids) == 1
                else None,
                source_chunk_count=len(value.source_chunk_ids),
                text_chars=len(value.text),
                start_seconds=value.start_time_sec,
                end_seconds=value.end_time_sec,
                timing_source=value.timing_source,
            )
        elif isinstance(value, OutputTranscriptChunk):
            fields.update(
                alignment_id=value.alignment_id,
                source_chunk_id=value.source_chunk_ids[0]
                if len(value.source_chunk_ids) == 1
                else None,
                source_chunk_count=len(value.source_chunk_ids),
                text_chars=len(value.text),
                interrupted=value.interrupted,
                state="final" if value.is_final else "chunk",
            )
        elif isinstance(value, OutputControl):
            fields.update(control_type=value.type.value, target_count=len(value.targets))
        elif isinstance(value, OutputStatusDecision):
            fields.update(state=value.state, event_kind=value.action)
        self._log("output.delivery", **fields)
        if isinstance(value, OutputControl) and value.type == OutputControlType.INTERRUPT:
            # Project the immutable targets, never resolve a late broad selector against new state.
            for target in value.targets[:32]:
                self._log(
                    "output.delivery",
                    **{
                        **fields,
                        "event_kind": "interrupt_target",
                        "output_id": target.output_id,
                        "context_id": target.scope.context_id,
                        "turn_id": target.scope.turn_id,
                        "run_id": target.scope.run_id,
                        "lane": target.lane.value,
                    },
                )
            if len(value.targets) > 32:
                self._log(
                    "output.delivery",
                    gap=True,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    missed_count=len(value.targets) - 32,
                    reason="target_projection_limit",
                )

    async def _output(self) -> None:
        dropped = 0
        while True:
            event = await self._subscription.get()
            total = self._subscription.dropped_count
            if total > dropped:
                self._log(
                    "output.delivery",
                    gap=True,
                    missed_count=total - dropped,
                    reason="observer_queue_overflow",
                )
                dropped = total
            self._output_event(event)

    async def _observe(self, factory, name: str) -> None:
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Optional diagnostics cannot change model or canonical record outcomes.
            self._log(name, gap=True, reason="observer_failed", error_type=type(error).__name__)

    async def _start(self) -> None:
        output = self._runtime.output
        self._subscription = await output.stream.subscribe(
            self.PREFIX,
            kinds=(
                OutputKind.TEXT_CHUNK,
                OutputKind.TRANSCRIPT_CHUNK,
                OutputKind.ALIGNMENT,
                OutputKind.PLAYBACK,
                OutputKind.CONTROL,
                OutputKind.STATUS,
            ),
            max_pending=256,
            reliable=False,
        )
        operations = [
            ("perception", self._perception),
            ("turn", self._turns),
            ("output.delivery", self._output),
        ]
        for name, stream in (
            ("output.execution", output.execution),
            ("output.records", output.records),
        ):
            consumer = f"{self.PREFIX}.{name}"
            stream.register(consumer, required=False)
            self._journals.append((stream, consumer))
            operations.append((name, partial(self._journal, stream, name, consumer)))
        for name, factory in operations:
            task = asyncio.create_task(self._observe(factory, name), name=f"diagnostics:{name}")
            self._tasks.append(task)

    async def on_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Event diagnostics are closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="event_trace_start")
        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None:
                raise RuntimeError("Event diagnostics closed during startup")
        except BaseException as original:
            try:
                await self.on_stop()
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
        errors = []
        try:
            if self._subscription is not None:
                await self._runtime.output.stream.unsubscribe(self.PREFIX)
        except Exception as error:
            errors.append(error)
        await asyncio.gather(*self._tasks, return_exceptions=True)
        operations = [partial(stream.unregister, consumer) for stream, consumer in self._journals]
        operations.extend(
            (
                partial(
                    self._runtime.perception.events.clear_consumer, f"{self.PREFIX}.perception"
                ),
                partial(self._runtime.turn.events.clear_consumer, f"{self.PREFIX}.turn"),
            )
        )
        for operation in operations:
            try:
                operation()
            except Exception as error:
                errors.append(error)
        self._tasks.clear()
        self._journals.clear()
        self._sampled.clear()
        self._subscription = None
        if errors:
            raise ExceptionGroup("Event diagnostic cleanup failed", errors)

    async def on_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="event_trace_close")
        await wait_for_cleanup(self._close_task)
