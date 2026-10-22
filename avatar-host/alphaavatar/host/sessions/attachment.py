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
from collections.abc import Awaitable, Callable, Sequence

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import LifecycleComponent, LifecycleGroup, LifecyclePhase

from .base import SessionConnection
from .schemas import SessionEnd


class SessionAttachment:
    """Own one connection and its adapters. Detachment never closes an execution."""

    def __init__(
        self,
        *,
        attachment_id: str,
        connection: SessionConnection,
        inputs: Sequence[LifecycleComponent] = (),
        outputs: Sequence[LifecycleComponent] = (),
        presentations: Sequence[LifecycleComponent] = (),
        failure_monitors: Sequence[Callable[[], Awaitable[None]]] = (),
        abort_ingress: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.attachment_id = attachment_id
        self.connection = connection

        self._inbound = LifecycleGroup((LifecyclePhase.create("session-input", inputs),))
        self._outbound = LifecycleGroup(
            (
                LifecyclePhase.create("session-presentation", presentations),
                LifecyclePhase.create("session-output", outputs),
            )
        )
        self._monitors, self._abort_ingress = tuple(failure_monitors), abort_ingress
        self._close_task: asyncio.Task[None] | None = None

    async def start_output(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Session attachment is closing or closed")
        await self._outbound.start()

    async def start_input(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Session attachment is closing or closed")
        await self._inbound.start()

    async def wait_ended(self) -> SessionEnd:
        connection = asyncio.create_task(
            self.connection.wait_ended(), name="session_connection_end"
        )
        monitors = [
            asyncio.create_task(wait(), name="session_adapter_monitor") for wait in self._monitors
        ]
        tasks = [connection, *monitors]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            # Failures win over an ordinary disconnection observed in the same loop turn.
            for task in monitors:
                if task in done:
                    await task
                    raise RuntimeError("Session adapter failure monitor returned without a failure")
            return await connection
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _close(self) -> None:
        errors: list[Exception] = []
        operations = []
        if self._abort_ingress is not None:
            operations.append(self._abort_ingress)
        operations.extend((self._inbound.stop, self._outbound.stop, self.connection.on_stop))
        for operation in operations:
            try:
                await operation()
            except asyncio.CancelledError as error:
                failure = RuntimeError("Session cleanup cancelled itself")
                failure.__cause__ = error
                errors.append(failure)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Session attachment cleanup failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="session_attachment_close")
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await wait_for_cleanup(self._close_task)
