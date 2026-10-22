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
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from alphaavatar.agents.avatar.provider.enums import ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.records import MODEL_RECORD_SCHEMA
from alphaavatar.agents.avatar.provider.schemas import ModelInput, ModelInputMessage, ModelTextPart
from alphaavatar.agents.avatar.provider.schemas.model_input import (
    ModelFunctionCall,
    ModelFunctionOutput,
)
from alphaavatar.core.cleanup import wait_for_cleanup

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.provider.schemas.model_input import ModelInputItem
    from alphaavatar.core.output import OutputRuntime
    from alphaavatar.core.output.schemas import OutputRecordBatch
    from alphaavatar.core.turn import TurnSnapshot

    from ..config import ContextConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Turn:
    context_id: str
    turn_id: str
    input_id: str
    cutoff: int
    seed: ModelInputMessage
    size_bytes: int
    records: list[tuple[str | None, ModelInputItem]] = field(default_factory=list)
    batch_digests: dict[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return 1 + len(self.records)

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
            self.seed,
            *(
                item
                for run_id, item in self.records
                if not isinstance(item, ModelFunctionCall | ModelFunctionOutput)
                or (run_id, item.call_id) in paired
            ),
        )


class ContextHistory:
    """Bounded canonical query history, independently acknowledging Output.records.

    User inputs come from committed Turns. Assistant/tool records come only from
    the lossless journal, not playout, LoopResult or private provider continuation.
    Byte accounting covers serialized content, not process RSS or shared media caches.
    """

    CONSUMER_ID = "context.history"

    def __init__(self, *, output: OutputRuntime, config: ContextConfig) -> None:
        self._journal = output.records
        self._max_turns = config.history_max_turns
        self._max_items = config.history_max_items
        self._max_bytes = config.history_max_bytes
        self._turns: OrderedDict[tuple[str, str], _Turn] = OrderedDict()
        self._bytes = self._items = self._latest_cutoff = 0
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

    def _evict(self, key: tuple[str, str]) -> None:
        removed = self._turns.pop(key)
        self._bytes -= removed.size_bytes
        self._items -= removed.count

    def _make_room(
        self, *, target: tuple[str, str], add_bytes: int, add_items: int, add_turn: bool = False
    ) -> bool:
        turn = self._turns.get(target)
        target_bytes = (turn.size_bytes if turn else 0) + add_bytes
        target_items = (turn.count if turn else 0) + add_items
        if target_bytes > self._max_bytes or target_items > self._max_items:
            raise RuntimeError("A single turn exceeds canonical context history capacity")

        victims = []
        size = self._bytes + add_bytes
        count = self._items + add_items
        turns = len(self._turns) + int(add_turn)
        for key, value in self._turns.items():
            if size <= self._max_bytes and count <= self._max_items and turns <= self._max_turns:
                break

            # Whole-turn eviction never leaves an orphan tool record in the projected input.
            if key == target:
                if key == next(reversed(self._turns)):
                    raise RuntimeError("The current turn cannot fit in context history")

                victims.append(key)
                break

            victims.append(key)
            size, count, turns = size - value.size_bytes, count - value.count, turns - 1

        for key in victims:
            self._evict(key)

        return target not in victims

    def _ingest(self, batch: OutputRecordBatch) -> None:
        if batch.schema != MODEL_RECORD_SCHEMA:
            return

        key = batch.scope.context_id, batch.scope.turn_id
        turn = self._turns.get(key)
        if turn is None:
            # A late result stays in canonical storage; it cannot resurrect an evicted query.
            return

        previous = turn.batch_digests.get(batch.batch_id)
        if previous is not None:
            if previous != batch.digest:
                raise ModelProtocolError("Conflicting canonical batch replay")
            return

        if not batch.items or type(batch.size_bytes) is not int or batch.size_bytes < 1:
            raise ModelProtocolError("Canonical history requires a nonempty measured batch")

        existing = {
            item.id
            for value in self._turns.values()
            if value.context_id == turn.context_id
            for item in (value.seed, *(item for _, item in value.records))
        }
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
            if item.id in existing:
                raise ModelProtocolError("Canonical model item identity was reused")

            existing.add(item.id)
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

        if not self._make_room(target=key, add_bytes=batch.size_bytes, add_items=len(records)):
            return

        turn.records.extend(records)
        turn.batch_digests[batch.batch_id] = batch.digest
        turn.size_bytes += batch.size_bytes
        self._bytes, self._items = self._bytes + batch.size_bytes, self._items + len(records)

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

    def accept_turn(self, snapshot: TurnSnapshot, context_id: str) -> ModelInput:
        self._start()
        key = context_id, snapshot.turn_id
        previous = self._turns.get(key)
        if previous is not None:
            if (previous.input_id, previous.cutoff) != (
                snapshot.input_id,
                snapshot.cutoff.sequence,
            ):
                raise ModelProtocolError("Committed turn identity changed")

            return ModelInput(items=(previous.seed,))

        if snapshot.cutoff.sequence < self._latest_cutoff:
            raise RuntimeError("This committed input is outside the retained context history")

        metadata = MappingProxyType(
            {
                "context_id": context_id,
                "turn_id": snapshot.turn_id,
                "input_modality": snapshot.modality.value,
            }
        )
        text = (
            snapshot.text
            if snapshot.text is not None
            else (
                '<historical_media omitted="true" current="false">'
                "Visual input belongs to this earlier turn; do not infer its contents from this placeholder."
                "</historical_media>"
            )
        )
        seed = ModelInputMessage(
            id=snapshot.input_id,
            role=ModelRole.USER,
            parts=(ModelTextPart(text),),
            created_at=snapshot.committed_at.unix_seconds,
            metadata=metadata,
        )
        size = len(
            json.dumps(
                {
                    "id": seed.id,
                    "text": text,
                    "metadata": dict(metadata),
                    "created_at": seed.created_at,
                },
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        )

        if any(
            value.context_id == context_id
            and (value.input_id == seed.id or any(item.id == seed.id for _, item in value.records))
            for value in self._turns.values()
        ):
            raise ModelProtocolError("Context input identity was reused")

        self._make_room(target=key, add_bytes=size, add_items=1, add_turn=True)
        self._turns[key] = _Turn(
            context_id, snapshot.turn_id, snapshot.input_id, snapshot.cutoff.sequence, seed, size
        )
        self._bytes, self._items = self._bytes + size, self._items + 1
        self._latest_cutoff = max(self._latest_cutoff, snapshot.cutoff.sequence)
        return ModelInput(items=(seed,))

    def capture(self, snapshot: TurnSnapshot, context_id: str, current: ModelInput) -> ModelInput:
        self._ensure_open()
        if (
            len(current.items) != 1
            or not isinstance(current.items[0], ModelInputMessage)
            or (current.items[0].id != snapshot.input_id or current.items[0].role != ModelRole.USER)
        ):
            raise ValueError(
                "Context preparation requires exactly the current committed input seed"
            )

        self.drain()
        key = context_id, snapshot.turn_id
        if key not in self._turns:
            raise RuntimeError("Current turn is not retained in context history")
        if current.realtime is not None or current.items != (self._turns[key].seed,):
            raise ValueError("Current input differs from its canonical committed Turn seed")

        items = []
        for entry_key, turn in self._turns.items():
            if entry_key == key:
                items.extend(current.items)
                break
            if turn.context_id == context_id:
                items.extend(turn.project())

        ids = [item.id for item in items]
        call_ids = [item.call_id for item in items if isinstance(item, ModelFunctionCall)]
        if len(ids) != len(set(ids)) or len(call_ids) != len(set(call_ids)):
            raise ModelProtocolError("Captured canonical history has duplicate identities")

        return ModelInput(items=tuple(items))

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
