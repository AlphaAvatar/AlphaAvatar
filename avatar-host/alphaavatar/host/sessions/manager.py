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

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.host.execution.execution import HostExecution

from .attachment import SessionAttachment


class SessionManager:
    """Single-attachment execution binding for v0.6.8, not a reconnection service."""

    def __init__(self) -> None:
        self._bindings: dict[str, tuple[HostExecution, SessionAttachment]] = {}
        self._retiring: dict[str, asyncio.Task[None]] = {}
        self._closed = False
        self._executions: set[HostExecution] = set()
        self._close_task: asyncio.Task[None] | None = None

    def register(self, execution: HostExecution, attachment: SessionAttachment) -> None:
        key = attachment.attachment_id
        if self._closed or key in self._bindings or key in self._retiring:
            raise RuntimeError("Session attachment cannot be registered")
        if execution in self._executions:
            raise RuntimeError("v0.6.8 does not rebind an execution to another attachment")

        self._executions.add(execution)
        self._bindings[key] = (execution, attachment)

    async def start(self, attachment_id: str) -> None:
        execution, attachment = self._bindings[attachment_id]
        try:
            await attachment.start_output()
            await execution.start()
            await attachment.start_input()
            if self._closed or attachment_id not in self._bindings:
                raise RuntimeError("Session detached during startup")

            execution.engine.notify_ready()
        except BaseException as original:
            try:
                await self.detach(attachment_id)
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def detach(self, attachment_id: str) -> None:
        task = self._retiring.get(attachment_id)
        if task is None:
            binding = self._bindings.pop(attachment_id, None)
            if binding is None:
                return
            _, attachment = binding
            task = asyncio.create_task(attachment.aclose(), name=f"session_detach:{attachment_id}")
            task.add_done_callback(lambda item: None if item.cancelled() else item.exception())
            self._retiring[attachment_id] = task
        await wait_for_cleanup(task)

    async def _close(self) -> None:
        results = await asyncio.gather(
            *(self.detach(key) for key in tuple(self._bindings)),
            *(wait_for_cleanup(task) for task in tuple(self._retiring.values())),
            return_exceptions=True,
        )
        errors = [item for item in results if isinstance(item, Exception)]
        if errors:
            raise ExceptionGroup("Session manager cleanup failed", errors)
        for item in results:
            if isinstance(item, BaseException):
                raise item

    async def aclose(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close(), name="session_manager_close")
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await wait_for_cleanup(self._close_task)
