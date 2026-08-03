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
import asyncio
from uuid import uuid4

from alphaavatar.agents.log import logger
from alphaavatar.agents.status.base import (
    StatusPolicyBase,
    StatusRendererBase,
    StatusSinkBase,
)
from alphaavatar.agents.status.schema import StatusEvent


class StatusEmitter:
    def __init__(
        self,
        *,
        renderer: StatusRendererBase | None = None,
        policy: StatusPolicyBase | None = None,
        sink: StatusSinkBase | None = None,
        enabled: bool = True,
    ) -> None:
        self._sink = sink
        self._renderer = renderer
        self._policy = policy
        self._enabled = enabled

        self._tasks: set[asyncio.Task] = set()
        self._current_turn_id: str | None = None

    @property
    def current_turn_id(self) -> str | None:
        return self._current_turn_id

    async def start_turn(self, *, turn_id: str | None = None) -> str:
        turn_id = turn_id or uuid4().hex
        self._current_turn_id = turn_id

        if self._policy is not None:
            self._policy.start_turn()

        if self._sink is not None:
            await self._sink.start_turn(
                turn_id=turn_id,
            )

        return turn_id

    async def emit(self, event: StatusEvent) -> None:
        if not self._enabled:
            return

        if self._sink is None:
            return

        if self._policy is not None and not self._policy.should_emit(event):
            return

        if self._renderer is None:
            return

        text = await self._renderer.render(event)
        if not text:
            return

        await self._sink.emit(event, text)

        if self._policy is not None:
            self._policy.mark_emitted(event)

    def emit_nowait(self, event: StatusEvent) -> asyncio.Task | None:
        if not self._enabled:
            return None

        try:
            task = asyncio.create_task(
                self.emit(event),
                name=(f"status_emit:{event.source}:{event.stage}"),
            )
        except RuntimeError:
            logger.debug(
                "Failed to schedule status event because no running event loop exists: %s",
                event,
            )
            return None

        self._track_task(task)
        return task

    def emit_delayed(
        self,
        event: StatusEvent,
        *,
        delay_sec: float | None = None,
    ) -> asyncio.Task | None:
        if not self._enabled:
            return None

        if delay_sec is None:
            delay_sec = self._policy.get_delay_sec(event) if self._policy is not None else 0.0

        try:
            task = asyncio.create_task(
                self._emit_after_delay(
                    event,
                    delay_sec=delay_sec,
                ),
                name=(f"status_emit_delayed:{event.source}:{event.stage}"),
            )
        except RuntimeError:
            logger.debug(
                "Failed to schedule delayed status event because no running event loop exists: %s",
                event,
            )
            return None

        self._track_task(task)
        return task

    async def _emit_after_delay(
        self,
        event: StatusEvent,
        *,
        delay_sec: float,
    ) -> None:
        if delay_sec > 0:
            await asyncio.sleep(delay_sec)

        await self.emit(event)

    def cancel_task(self, task: asyncio.Task | None) -> None:
        if task is not None and not task.done():
            task.cancel()

    def cancel_all(self) -> None:
        for task in tuple(self._tasks):
            if not task.done():
                task.cancel()

    def _track_task(self, task: asyncio.Task) -> None:
        self._tasks.add(task)

        def _cleanup(completed_task: asyncio.Task) -> None:
            self._tasks.discard(completed_task)

            try:
                exception = completed_task.exception()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("Failed to inspect status task result: %s", exc)
                return

            if exception is not None:
                logger.warning("Status event task failed: %s", exception)

        task.add_done_callback(_cleanup)
