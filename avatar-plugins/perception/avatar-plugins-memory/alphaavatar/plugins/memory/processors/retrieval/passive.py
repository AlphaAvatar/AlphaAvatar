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
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from alphaavatar.agents.memory.schemas import MemoryItem, MemoryOwnerRef
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnSnapshot

from .config import RetrievalConfig

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime

    from ...runtime import MemoryRuntime

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Recall:
    turn_id: str
    sequence: int
    deadline: float
    result: asyncio.Future[str]
    task: asyncio.Task[None] | None = None
    timer: asyncio.TimerHandle | None = None


class PassiveRecall:
    """Consume committed Turns, update shared memory, and expose completion without data."""

    CONSUMER_ID = "memory.retrieval.turn"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        memory: MemoryRuntime,
        config: RetrievalConfig,
        notify: Callable[[Iterable[MemoryItem]], None],
    ) -> None:
        self._runtime = runtime
        self._memory = memory
        self._config = config
        self._notify = notify
        self._entries: OrderedDict[str, _Recall] = OrderedDict()
        self._history: OrderedDict[str, deque[str]] = OrderedDict()
        self._inflight: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._expired: set[int] = set()
        self._consumer: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._accepting = False

    def _finish(self, entry: _Recall, status: str, *, count: int = 0) -> None:
        if entry.result.done():
            return
        if entry.timer is not None:
            entry.timer.cancel()
            entry.timer = None
        entry.result.set_result(status)
        elapsed = (
            asyncio.get_running_loop().time() - entry.deadline + self._config.passive_timeout_sec
        )
        logger.debug(
            "MEMORY PASSIVE RECALL turn_id=%s status=%s elapsed_ms=%.1f items=%d inflight=%d",
            entry.turn_id,
            status,
            elapsed * 1000,
            count,
            len(self._inflight),
        )

    def _expire(self, entry: _Recall) -> None:
        self._finish(entry, "timeout")
        if entry.task is None:
            self._inflight.discard(entry.turn_id)
        else:
            entry.task.cancel()

    def _prune_expired(self) -> None:
        batch = self._runtime.turn.events.read_pending(consumer_id=self.CONSUMER_ID, limit=1)
        floor = max(
            batch.committed_cursor_seq, (batch.first_available_seq or batch.latest_seq + 1) - 1
        )
        self._expired = {sequence for sequence in self._expired if sequence > floor}

    def _entry(self, snapshot: TurnSnapshot, sequence: int) -> _Recall | None:
        if entry := self._entries.get(snapshot.turn_id):
            return entry
        if sequence in self._expired:
            return None
        while len(self._entries) >= self._config.max_retained_turns:
            key = next((key for key in self._entries if key not in self._inflight), None)
            if key is None:
                return None
            self._expired.add(self._entries.pop(key).sequence)
            self._prune_expired()
        loop = asyncio.get_running_loop()
        age = max(0.0, self._runtime.perception.clock.now().elapsed_since(snapshot.committed_at))
        entry = _Recall(
            turn_id=snapshot.turn_id,
            sequence=sequence,
            deadline=loop.time() + self._config.passive_timeout_sec - age,
            result=loop.create_future(),
        )
        self._entries[entry.turn_id] = entry
        if len(self._inflight) >= self._config.max_pending_recalls:
            self._finish(entry, "overloaded")
        else:
            self._inflight.add(entry.turn_id)
            entry.timer = loop.call_at(entry.deadline, self._expire, entry)
        return entry

    def _remember(self, snapshot: TurnSnapshot) -> str | None:
        if snapshot.modality == TurnInputModality.SYSTEM or not snapshot.text:
            return None
        context_id = self._memory.resolve_context_id(snapshot.context_ids)
        text = snapshot.text[-self._config.max_query_chars :].strip()
        if context_id is None or not text:
            return None
        history = self._history.setdefault(context_id, deque(maxlen=self._config.search_context))
        history.append(text)
        self._history.move_to_end(context_id)
        while len(self._history) > self._config.max_retained_turns:
            self._history.popitem(last=False)
        return context_id

    async def _run(self, entry: _Recall, context_id: str, query: str) -> None:
        try:
            async with asyncio.timeout_at(entry.deadline):
                state = self._memory.context_state(context_id)
                owners = list(
                    {
                        ref.key: ref
                        for ref in (
                            MemoryOwnerRef.avatar(self._memory.avatar_id),
                            *state.owner_refs,
                        )
                    }.values()
                )
                remaining = entry.deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self._finish(entry, "timeout")
                    return
                items = await self._memory.store.recall_by_context(
                    context_str=query,
                    owner_refs=owners,
                    context=state.context,
                    top_k=self._config.recall_num,
                    timeout=remaining,
                    trace_id=entry.turn_id,
                )
            # Cancellation-resistant transports must never publish after the owned deadline.
            if asyncio.get_running_loop().time() >= entry.deadline:
                self._finish(entry, "timeout")
            elif not entry.result.done():
                self._memory.apply_items(items)
                self._finish(entry, "ok" if items else "empty", count=len(items))
                try:
                    self._notify(items)
                except Exception as error:
                    logger.warning(
                        "Memory recall observer failed turn_id=%s error_type=%s",
                        entry.turn_id,
                        type(error).__name__,
                    )
        except TimeoutError:
            self._finish(entry, "timeout")
        except asyncio.CancelledError:
            self._finish(entry, "unavailable")
            raise
        except Exception as error:
            self._finish(entry, "error")
            logger.warning(
                "Memory recall failed turn_id=%s error_type=%s", entry.turn_id, type(error).__name__
            )

    def _task_done(self, entry: _Recall, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        self._inflight.discard(entry.turn_id)
        entry.task = None
        if task.cancelled():
            self._finish(entry, "unavailable")
        elif task.exception() is not None:
            self._finish(entry, "error")

    async def _schedule(self, snapshot: TurnSnapshot, sequence: int) -> None:
        # Even an overloaded Turn belongs in subsequent conversational recall queries.
        context_id = self._remember(snapshot)
        entry = self._entry(snapshot, sequence)
        if entry is None or entry.result.done():
            if entry is not None and entry.task is None:
                self._inflight.discard(entry.turn_id)
            return
        try:
            if snapshot.modality == TurnInputModality.SYSTEM or not (snapshot.text or "").strip():
                self._finish(entry, "empty")
                return
            async with asyncio.timeout_at(entry.deadline):
                await self._runtime.turn.events.wait_until_consumed(
                    consumer_id=self._memory.TURN_CONSUMER_ID, cursor_seq=sequence
                )
            if entry.result.done() or asyncio.get_running_loop().time() >= entry.deadline:
                self._finish(entry, "timeout")
                return
            if context_id is None:
                self._finish(entry, "unavailable")
                return
            query = "\n\n".join(f"### user:\n{text}" for text in self._history[context_id])
            entry.task = asyncio.create_task(
                self._run(entry, context_id, query[-self._config.max_query_chars :]),
                name=f"memory_passive_recall:{entry.turn_id}",
            )
            self._tasks.add(entry.task)
            entry.task.add_done_callback(lambda task: self._task_done(entry, task))
        except TimeoutError:
            self._finish(entry, "timeout")
        except asyncio.CancelledError:
            self._finish(entry, "unavailable")
            raise
        except Exception as error:
            self._finish(entry, "error")
            logger.warning(
                "Memory recall scheduling failed turn_id=%s error_type=%s",
                entry.turn_id,
                type(error).__name__,
            )
        finally:
            if entry.task is None:
                self._inflight.discard(entry.turn_id)

    async def _consume(self) -> None:
        stream = self._runtime.turn.events
        try:
            while True:
                await stream.wait_for_pending(consumer_id=self.CONSUMER_ID)
                batch = stream.read_pending(consumer_id=self.CONSUMER_ID, limit=1)
                if batch.has_gap:
                    logger.warning(
                        "Memory recall missed committed turns missed=%d", batch.missed_count
                    )
                for event in batch.items:
                    await self._schedule(event.snapshot, event.sequence)
                stream.commit(consumer_id=self.CONSUMER_ID, cursor_seq=batch.cursor_seq)
                self._prune_expired()
        finally:
            self._accepting = False
            for entry in self._entries.values():
                self._finish(entry, "unavailable")

    async def wait_context_ready(self, snapshot: TurnSnapshot) -> None:
        if self._runtime.turn.get(snapshot.input_id) is not snapshot:
            raise ValueError("Memory readiness requires a Turn owned by this runtime")
        if not self._accepting:
            return
        entry = self._entries.get(snapshot.turn_id)
        if entry is None:
            batch = self._runtime.turn.events.read_pending(consumer_id=self.CONSUMER_ID)
            event = next((event for event in batch.items if event.snapshot is snapshot), None)
            if event is None:
                return
            entry = self._entry(snapshot, event.sequence)
        if entry is not None:
            await asyncio.shield(entry.result)

    def _consumer_done(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Memory recall consumer failed error_type=%s", type(error).__name__)

    async def start(self) -> None:
        if self._stop_task is not None:
            raise RuntimeError("Passive recall cannot restart after stopping")
        self._accepting = True
        self._runtime.turn.register_context_consumer(
            self.CONSUMER_ID, waiter=self.wait_context_ready
        )
        self._consumer = asyncio.create_task(self._consume(), name="memory_retrieval_turn_consumer")
        self._consumer.add_done_callback(self._consumer_done)

    async def _stop(self) -> None:
        self._accepting = False
        if self._consumer is not None:
            self._consumer.cancel()
            await asyncio.gather(self._consumer, return_exceptions=True)
            self._consumer = None
        for entry in self._entries.values():
            self._finish(entry, "unavailable")
        self._runtime.turn.unregister_context_consumer(self.CONSUMER_ID)
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._entries.clear()
        self._inflight.clear()
        self._history.clear()
        self._expired.clear()
        self._runtime.turn.events.clear_consumer(self.CONSUMER_ID)

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop(), name="memory_passive_recall_stop")
        await wait_for_cleanup(self._stop_task)
