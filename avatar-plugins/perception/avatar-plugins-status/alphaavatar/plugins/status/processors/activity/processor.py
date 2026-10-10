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
from typing import TYPE_CHECKING

from alphaavatar.agents.status import StatusProcessorBase
from alphaavatar.core.output.enums import OutputControlType, OutputKind, OutputLane
from alphaavatar.core.output.schemas import OutputControl, OutputExecutionSignal, OutputTextChunk

from ...state import StatusState
from .config import ActivityConfig

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime

logger = logging.getLogger(__name__)


class ActivityProcessor(StatusProcessorBase):
    TURN_ID = "status.activity.turn"
    EXECUTION_ID = "status.activity.execution"
    DELIVERY_ID = "status.activity.delivery"

    def __init__(self, runtime: AvatarRuntime, state: StatusState, config: ActivityConfig) -> None:
        self._runtime, self._state, self._config = runtime, state, config
        self._tasks: list[asyncio.Task] = []
        self._subscription = None
        self._registered = False

    def _drain_turns(self) -> None:
        stream = self._runtime.turn.events
        while True:
            batch = stream.read_pending(consumer_id=self.TURN_ID, limit=32)
            if batch.has_gap:
                logger.warning("Status missed %s turn observations", batch.missed_count)

            for event in batch.items:
                turn = event.snapshot
                if turn.context_ids:
                    self._state.turn(
                        turn_id=turn.turn_id,
                        context_id=turn.context_ids[0],
                        at_ns=turn.committed_at.monotonic_ns,
                        event_id=event.event_id,
                    )

            stream.commit(consumer_id=self.TURN_ID, cursor_seq=batch.cursor_seq)
            if not batch.items or batch.remaining_count == 0:
                return

    async def _turns(self) -> None:
        stream = self._runtime.turn.events
        while True:
            await stream.wait_for_pending(consumer_id=self.TURN_ID)
            self._drain_turns()
            await asyncio.sleep(0)

    def _drain_execution(self) -> None:
        stream = self._runtime.output.execution
        self._drain_turns()
        while True:
            batch = stream.read_pending(consumer_id=self.EXECUTION_ID, limit=32)
            if batch.has_gap:
                logger.warning("Status missed %s execution observations", batch.missed_count)

            for event in batch.items:
                if isinstance(event.payload, OutputExecutionSignal):
                    self._state.signal(event.event_id, event.payload)

            stream.commit(consumer_id=self.EXECUTION_ID, cursor_seq=batch.cursor_seq)
            if not batch.items or batch.cursor_seq >= batch.latest_seq:
                return

    async def _execution(self) -> None:
        stream = self._runtime.output.execution
        while await stream.wait_for_pending(consumer_id=self.EXECUTION_ID):
            self._drain_execution()
            await asyncio.sleep(0)

    async def _delivery(self) -> None:
        while True:
            event = await self._subscription.get()

            # Independent subscriptions can be scheduled in either order.
            self._drain_execution()
            if event.kind == OutputKind.TEXT_CHUNK and isinstance(event.payload, OutputTextChunk):
                if event.payload.text.strip() and (run_id := event.metadata.get("run_id")):
                    self._state.text(
                        run_id=run_id,
                        request_id=event.metadata.get("request_id"),
                        event_id=event.event_id,
                    )

            elif isinstance(event.payload, OutputControl):
                control = event.payload
                if control.type != OutputControlType.INTERRUPT:
                    continue

                # Replacing transient speech or one completed message is not a Run interruption.
                if (
                    control.target_lane == OutputLane.TRANSIENT
                    or control.target_output_id
                    or event.metadata.get("replacement_output_id")
                    or event.metadata.get("assistant_output_id")
                ):
                    continue

                self._state.interrupt(
                    run_id=event.metadata.get("run_id"),
                    turn_id=control.target_turn_id,
                    event_id=event.event_id,
                )

    async def _observe(self, operation) -> None:
        try:
            await operation
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Status observation consumer stopped")

    async def start(self) -> None:
        if self._tasks:
            return

        self._runtime.output.execution.register(self.EXECUTION_ID)
        self._registered = True
        self._subscription = await self._runtime.output.stream.subscribe(
            self.DELIVERY_ID,
            kinds=(OutputKind.TEXT_CHUNK, OutputKind.CONTROL),
            lanes=(OutputLane.ASSISTANT,),
            max_pending=self._config.max_pending,
            reliable=False,
        )
        for label, operation in (
            ("turn", self._turns()),
            ("execution", self._execution()),
            ("delivery", self._delivery()),
        ):
            task = asyncio.create_task(self._observe(operation), name=f"status:{label}")
            self._tasks.append(task)

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        if self._subscription is not None:
            await self._runtime.output.stream.unsubscribe(self.DELIVERY_ID)
            self._subscription = None
        if self._registered:
            self._runtime.output.execution.unregister(self.EXECUTION_ID)
            self._registered = False
        self._runtime.turn.events.clear_consumer(self.TURN_ID)
