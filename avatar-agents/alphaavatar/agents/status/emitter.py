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
from typing import Any

from alphaavatar.agents.log import logger
from alphaavatar.agents.status.base import (
    StatusPolicyBase,
    StatusRendererBase,
    StatusSinkBase,
)
from alphaavatar.agents.status.callback import StatusSink
from alphaavatar.agents.status.enum import StatusVisibility
from alphaavatar.agents.status.schema import StatusEvent


class StatusEmitter:
    def __init__(
        self,
        *,
        sink: StatusSink | StatusSinkBase | None = None,
        renderer: StatusRendererBase | None = None,
        policy: StatusPolicyBase | None = None,
        enabled: bool = True,
    ):
        self._sink = sink
        self._renderer = renderer
        self._policy = policy
        self._enabled = enabled
        self._tasks: set[asyncio.Task] = set()

    def bind_engine(self, engine: Any) -> None:
        if self._renderer is not None:
            self._renderer.bind_engine(engine)

        if self._policy is not None:
            self._policy.bind_engine(engine)

        if isinstance(self._sink, StatusSinkBase):
            self._sink.bind_engine(engine)

    def set_sink(self, sink: StatusSink | StatusSinkBase | None):
        self._sink = sink

    def start_turn(self):
        if self._policy is not None:
            self._policy.start_turn()

    async def emit(self, event: StatusEvent) -> None:
        if not self._enabled:
            return

        if self._sink is None:
            return

        if event.visibility == StatusVisibility.SILENT:
            return

        if self._policy is not None and not self._policy.should_emit(event):
            return

        text: str | None = None

        if event.visibility != StatusVisibility.EVENT and event.render_mode != "none":
            if self._renderer is None:
                return

            text = await self._renderer.render(event)

            if not text:
                return

        await self._emit_to_sink(event, text)

        if self._policy is not None:
            self._policy.mark_emitted()

    def emit_nowait(self, event: StatusEvent) -> asyncio.Task | None:
        """
        Fire-and-forget status event.

        This is the preferred path before long-running operations.
        The actual status delivery is scheduled asynchronously and will not block
        the caller.
        """
        if not self._enabled:
            return None

        try:
            task = asyncio.create_task(self.emit(event))
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
        """
        Schedule a delayed status event.

        If delay_sec is None, StatusEmitter asks the policy for the delay.
        This keeps delayed status behavior centralized in the status layer.
        """
        if not self._enabled:
            return None

        if delay_sec is None:
            delay_sec = self._policy.get_delay_sec(event) if self._policy is not None else 0.0

        try:
            task = asyncio.create_task(self._emit_after_delay(event, delay_sec=delay_sec))
        except RuntimeError:
            logger.debug(
                "Failed to schedule delayed status event because no running event loop exists: %s",
                event,
            )
            return None

        self._track_task(task)
        return task

    async def _emit_after_delay(self, event: StatusEvent, *, delay_sec: float) -> None:
        if delay_sec > 0:
            await asyncio.sleep(delay_sec)

        await self.emit(event)

    def cancel_task(self, task: asyncio.Task | None) -> None:
        if task is None:
            return

        if not task.done():
            task.cancel()

    def cancel_all(self) -> None:
        for task in list(self._tasks):
            if not task.done():
                task.cancel()

    def _track_task(self, task: asyncio.Task) -> None:
        self._tasks.add(task)

        def _cleanup(t: asyncio.Task) -> None:
            self._tasks.discard(t)

            try:
                exc = t.exception()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug("Failed to inspect status task result: %s", e)
                return

            if exc is not None:
                logger.warning("Status event task failed: %s", exc)

        task.add_done_callback(_cleanup)

    async def _emit_to_sink(self, event: StatusEvent, text: str | None) -> None:
        if self._sink is None:
            return

        if isinstance(self._sink, StatusSinkBase):
            await self._sink.emit(event, text)
            return

        await self._sink(event, text)
