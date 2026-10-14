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
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING

from livekit import api

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.host.execution import HostExecution
from alphaavatar.rtc.livekit.utils.events import RoomEventBindings

if TYPE_CHECKING:
    from livekit.agents import JobContext

    from alphaavatar.agents.avatar import AvatarEngine
    from alphaavatar.rtc.livekit.text import LiveKitTextInput

logger = logging.getLogger(__name__)


class LiveKitConnection:
    """Own transport events and monitors, delegating execution resources to HostExecution."""

    def __init__(
        self,
        *,
        ctx: JobContext,
        execution: HostExecution,
        engine: AvatarEngine,
        participant_identity: str,
        text_input: LiveKitTextInput | None = None,
        max_duration: int = 1800,
    ) -> None:
        if type(max_duration) is not int or max_duration < 0:
            raise ValueError("max_duration must be a nonnegative integer")

        self._ctx, self._execution, self._engine = ctx, execution, engine
        self._participant, self._text = participant_identity, text_input

        self._events = RoomEventBindings(ctx.room)
        self._max_duration = max_duration
        self._tasks: set[asyncio.Task[None]] = set()
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._reason = "host_shutdown"
        self._failure: Exception | None = None
        self._ingress_failure = False

    @staticmethod
    async def _step(operation: Awaitable[None], errors: list[Exception], label: str) -> None:
        try:
            await operation
        except asyncio.CancelledError as error:
            failure = RuntimeError(f"{label} cancelled itself")
            failure.__cause__ = error
            errors.append(failure)
        except Exception as error:
            errors.append(error)

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Native Host cleanup failed", exc_info=error)

    def _spawn(self, operation: Coroutine[None, None, None], name: str) -> None:
        task = asyncio.create_task(operation, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._observe)

    def _observe(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            if self._close_task is None:
                self._failure = self._failure or RuntimeError(
                    f"Host monitor cancelled unexpectedly: {task.get_name()}"
                )
                self._ensure_close("host_monitor_cancelled")
        elif (error := task.exception()) is not None:
            self._failure = self._failure or error
            self._ensure_close("host_monitor_failed")

    async def _monitor(self, wait: Callable[[], Awaitable[None]], *, ingress: bool = False) -> None:
        try:
            await wait()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._failure = self._failure or error
            self._ingress_failure = self._ingress_failure or ingress
            self._ensure_close("native_input_failed" if ingress else "native_execution_failed")
        else:
            self._failure = self._failure or RuntimeError(
                "Failure monitor returned without a failure"
            )
            self._ensure_close("invalid_failure_monitor")

    async def _watchdog(self) -> None:
        await asyncio.sleep(self._max_duration)
        self._ensure_close("max_session_duration")

    async def _start(self) -> None:
        @self._events.on("participant_disconnected")
        def disconnected(participant) -> None:
            if participant.identity == self._participant:
                self._ensure_close("linked_participant_disconnected")

        @self._events.on("disconnected")
        def room_disconnected(*_) -> None:
            self._ensure_close("room_disconnected")

        self._spawn(self._monitor(self._engine.wait_failed), "avatar_engine_monitor")
        if self._text is not None:
            self._spawn(self._monitor(self._text.wait_failed, ingress=True), "avatar_text_monitor")

        await self._execution.start()
        if self._close_task is not None:
            raise RuntimeError("Connection closed during startup")

        self._engine.notify_ready()
        if self._max_duration > 0:
            self._spawn(self._watchdog(), "avatar_session_watchdog")

    async def start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Connection is closing")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="avatar_connection_start")
        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None:
                raise RuntimeError("Connection closed during startup")
        except BaseException as original:
            try:
                await self.aclose()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def _disconnect(self) -> None:
        async with asyncio.timeout(5.0):
            await self._ctx.room.disconnect()

    async def _delete_room(self) -> None:
        client = api.LiveKitAPI()
        try:
            async with asyncio.timeout(5.0):
                await client.room.delete_room(api.DeleteRoomRequest(room=self._ctx.room.name))
        finally:
            await client.aclose()

    async def _close(self) -> None:
        errors: list[Exception] = []
        try:
            self._events.clear()
        except Exception as error:
            errors.append(error)
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        pending = tuple(self._tasks)
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        # Abort bounded ingress readers before waiting for execution settlement.
        if self._ingress_failure or (self._text is not None and self._text.has_pending_streams):
            await self._step(self._disconnect(), errors, "Ingress disconnection")

        await self._step(self._execution.aclose(), errors, "Execution shutdown")
        await self._step(self._delete_room(), errors, "Room deletion")
        await self._step(self._disconnect(), errors, "Room disconnection")

        try:
            self._ctx.shutdown(reason=self._reason)
        except Exception as error:
            errors.append(error)
        if self._failure is not None:
            errors.insert(0, self._failure)
        if errors:
            raise ExceptionGroup("LiveKit connection cleanup failed", errors)

    def _ensure_close(self, reason: str) -> asyncio.Task[None]:
        if self._close_task is None:
            self._reason = reason
            self._close_task = asyncio.create_task(self._close(), name="avatar_connection_close")
            self._close_task.add_done_callback(self._observe_close)
        return self._close_task

    async def aclose(self) -> None:
        await wait_for_cleanup(self._ensure_close("host_shutdown"))
