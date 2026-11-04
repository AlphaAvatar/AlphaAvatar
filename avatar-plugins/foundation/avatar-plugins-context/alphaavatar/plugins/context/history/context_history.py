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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from alphaavatar.agents.avatar.provider.enums import ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.records import MODEL_RECORD_SCHEMA
from alphaavatar.agents.avatar.provider.schemas import (
    ModelInput,
    ModelInputMessage,
    RealtimeModelInput,
)
from alphaavatar.agents.avatar.provider.schemas.model_input import (
    ModelFunctionCall,
    ModelFunctionOutput,
)
from alphaavatar.agents.constants import RUNTIME_CONTEXT_TOOL_NAME
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.turn import TurnStream

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.provider.schemas.model_input import ModelInputItem
    from alphaavatar.core.output import OutputRuntime
    from alphaavatar.core.output.schemas import OutputRecordBatch
    from alphaavatar.core.turn.schemas import TurnSnapshot

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Turn:
    context_id: str
    turn_id: str
    cutoff: int
    message: ModelInputMessage
    realtime: RealtimeModelInput | None
    records: list[tuple[str | None, ModelInputItem]] = field(default_factory=list)
    batch_digests: dict[str, str] = field(default_factory=dict)

    def project(self) -> tuple[ModelInputItem, ...]:
        # A retiring tool may settle after another query begins. Never expose half a pair.
        calls = {
            (run_id, item.call_id)
            for run_id, item in self.records
            if isinstance(item, ModelFunctionCall)
        }
        outputs = {
            (run_id, item.call_id)
            for run_id, item in self.records
            if isinstance(item, ModelFunctionOutput)
        }
        paired = calls & outputs
        return (
            self.message,
            *(
                item
                for run_id, item in self.records
                if not isinstance(item, ModelFunctionCall | ModelFunctionOutput)
                or (run_id, item.call_id) in paired
            ),
        )


class ContextHistory:
    """Canonical session history, independently acknowledging Output.records.

    User messages come from ContextBuilder. Assistant and tool records come from Output.records.
    """

    CONSUMER_ID = "context.history"

    def __init__(self, *, output: OutputRuntime, turns: TurnStream) -> None:
        self._journal = output.records
        self._turn_events = turns
        self._turns: dict[tuple[str, str], _Turn] = {}
        self._item_ids: dict[str, set[str]] = {}
        self._capture_lock = asyncio.Lock()
        self._registered = self._stopping = False
        self._worker: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._failure: Exception | None = None

    def _ensure_open(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Context history is closing or closed")
        if self._failure is not None:
            raise RuntimeError("Context history consumer has failed") from self._failure

    def _fail(self, error: BaseException) -> None:
        if isinstance(error, asyncio.CancelledError):
            failure = RuntimeError("Context history consumer cancelled without owner shutdown")
            failure.__cause__ = error
        elif isinstance(error, Exception):
            failure = error
        else:
            raise error
        if self._failure is None:
            self._failure = failure
            if self._registered:
                self._journal.fail(self.CONSUMER_ID, failure)
            logger.error("Context history consumer failed", exc_info=failure)

    def _observe(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            if not self._stopping:
                self._fail(asyncio.CancelledError())
        elif (error := task.exception()) is not None:
            self._fail(error)

    def _start(self) -> None:
        self._ensure_open()
        if not self._registered:
            self._journal.register(self.CONSUMER_ID, required=True)
            self._registered = True
            self._worker = asyncio.create_task(self._run(), name=self.CONSUMER_ID)
            self._worker.add_done_callback(self._observe)

    def _ingest(self, batch: OutputRecordBatch) -> None:
        if batch.schema != MODEL_RECORD_SCHEMA:
            return

        key = batch.scope.context_id, batch.scope.turn_id
        turn = self._turns.get(key)
        if turn is None:
            # Output for a turn outside this history has no owning entry here.
            return

        previous = turn.batch_digests.get(batch.batch_id)
        if previous is not None:
            if previous != batch.digest:
                raise ModelProtocolError("Conflicting canonical batch replay")
            return

        if not batch.items or type(batch.size_bytes) is not int or batch.size_bytes < 1:
            raise ModelProtocolError("Canonical history requires a nonempty measured batch")

        existing = self._item_ids[turn.context_id]
        added: set[str] = set()
        run_id = batch.scope.run_id
        if not isinstance(run_id, str) or not run_id:
            raise ModelProtocolError("Canonical model records require their owning run")

        calls = {
            (owner, item.call_id): item
            for owner, item in turn.records
            if isinstance(item, ModelFunctionCall)
        }
        output_ids = {
            (owner, item.call_id)
            for owner, item in turn.records
            if isinstance(item, ModelFunctionOutput)
        }
        records = []
        for item in batch.items:
            if (
                isinstance(item, ModelFunctionCall | ModelFunctionOutput)
                and item.name == RUNTIME_CONTEXT_TOOL_NAME
            ):
                continue
            if item.id in existing or item.id in added:
                raise ModelProtocolError("Canonical model item identity was reused")

            added.add(item.id)
            if isinstance(item, ModelInputMessage):
                if item.role != ModelRole.ASSISTANT:
                    raise ModelProtocolError(
                        "Output history cannot contain user or policy messages"
                    )
            elif isinstance(item, ModelFunctionCall):
                if (run_id, item.call_id) in calls:
                    raise ModelProtocolError("Canonical tool call identity was reused")
                calls[run_id, item.call_id] = item
            elif isinstance(item, ModelFunctionOutput):
                call = calls.get((run_id, item.call_id))
                if call is None or call.name != item.name or (run_id, item.call_id) in output_ids:
                    raise ModelProtocolError("Canonical tool output has no unique owning call")
                output_ids.add((run_id, item.call_id))
            else:
                raise ModelProtocolError("Private continuation cannot enter canonical history")

            records.append((run_id, item))

        turn.records.extend(records)
        turn.batch_digests[batch.batch_id] = batch.digest
        existing.update(added)

    def drain(self) -> None:
        if not self._registered:
            return

        if self._failure is not None:
            raise RuntimeError("Context history consumer failed") from self._failure

        try:
            while True:
                read = self._journal.read_pending(consumer_id=self.CONSUMER_ID)
                if read.has_gap:
                    raise RuntimeError("Context history missed canonical records")

                for event in read.items:
                    if event.scope != event.payload.scope:
                        raise ModelProtocolError("Canonical batch scope changed")

                    self._ingest(event.payload)
                    self._journal.commit(consumer_id=self.CONSUMER_ID, cursor_seq=event.sequence)

                if read.cursor_seq >= read.latest_seq:
                    return
        except BaseException as error:
            self._fail(error)
            raise

    def _accept_turn(self, snapshot: TurnSnapshot, built: ModelInput) -> None:
        message = built.get(snapshot.input_id)
        if not isinstance(message, ModelInputMessage) or message.role != ModelRole.USER:
            raise ModelProtocolError("Committed turn requires a built user message")

        for context_id in snapshot.context_ids:
            key = context_id, snapshot.turn_id
            if previous := self._turns.get(key):
                if (previous.message.id, previous.cutoff) != (
                    snapshot.input_id,
                    snapshot.cutoff.sequence,
                ):
                    raise ModelProtocolError("Committed turn identity changed")
                continue

            existing = self._item_ids.setdefault(context_id, set())
            if message.id in existing:
                raise ModelProtocolError("Context input identity was reused")
            self._turns[key] = _Turn(
                context_id, snapshot.turn_id, snapshot.cutoff.sequence, message, built.realtime
            )
            existing.add(message.id)

    async def _accept_through(
        self,
        snapshot: TurnSnapshot,
        context_id: str,
        build: Callable[[TurnSnapshot, ModelInput], Awaitable[ModelInput]],
    ) -> ModelInput:
        # Read from the commit stream so a superseded run still contributes its input.
        stream = self._turn_events
        batch = stream.read_pending(consumer_id=self.CONSUMER_ID)
        end = next(
            (index + 1 for index, event in enumerate(batch.items) if event.snapshot is snapshot),
            None,
        )
        if end is None:
            raise RuntimeError("Current turn is not retained in context history")
        if batch.has_gap:
            logger.warning(
                "Context history missed %d committed turns; using the retained tail",
                batch.missed_count,
            )

        cursor = batch.committed_cursor_seq
        try:
            for event in batch.items[:end]:
                turn = event.snapshot
                if turn is snapshot:
                    self.drain()
                    result = await build(turn, self._project(context_id))
                    self._accept_turn(turn, result)
                    cursor = event.sequence
                    return result
                if turn.context_ids:
                    self._accept_turn(turn, await build(turn, ModelInput(items=())))
                cursor = event.sequence
        finally:
            if cursor > batch.committed_cursor_seq:
                stream.commit(consumer_id=self.CONSUMER_ID, cursor_seq=cursor)

        raise RuntimeError("Current turn is not retained in context history")

    async def capture(
        self,
        snapshot: TurnSnapshot,
        context_id: str,
        build: Callable[[TurnSnapshot, ModelInput], Awaitable[ModelInput]],
    ) -> ModelInput:
        async with self._capture_lock:
            self._start()
            key = context_id, snapshot.turn_id
            if key not in self._turns:
                return await self._accept_through(snapshot, context_id, build)

            self.drain()
            return await build(snapshot, self._project(context_id, current=key))

    def _project(self, context_id: str, *, current: tuple[str, str] | None = None) -> ModelInput:
        items = []
        realtime = None
        for entry_key, turn in self._turns.items():
            if entry_key == current:
                items.append(turn.message)
                realtime = turn.realtime
                break
            if turn.context_id == context_id:
                items.extend(turn.project())

        ids = [item.id for item in items]
        call_ids = [item.call_id for item in items if isinstance(item, ModelFunctionCall)]
        if len(ids) != len(set(ids)) or len(call_ids) != len(set(call_ids)):
            raise ModelProtocolError("Captured canonical history has duplicate identities")

        return ModelInput(items=tuple(items), realtime=realtime)

    async def _run(self) -> None:
        while await self._journal.wait_for_pending(consumer_id=self.CONSUMER_ID):
            self.drain()

    async def _close(self) -> None:
        errors = []
        try:
            self.drain()
        except Exception as error:
            errors.append(error)
        if self._worker is not None:
            if not self._worker.done() and not self._worker.cancelling():
                self._stopping = True
                self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._observe(self._worker)

        self._turn_events.clear_consumer(self.CONSUMER_ID)
        if self._registered and self._failure is None:
            self._journal.unregister(self.CONSUMER_ID)
            self._registered = False
        if self._failure is not None and self._failure not in errors:
            errors.append(self._failure)
        if errors:
            raise ExceptionGroup("Context history cleanup failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="context_history_close")
        await wait_for_cleanup(self._close_task)
