# Copyright 2025 AlphaAvatar project
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
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from alphaavatar.agents.runtime.capability import AvatarCapability
from alphaavatar.agents.runtime.plugin import AvatarRuntimePlugin
from alphaavatar.core.cleanup import wait_for_cleanup

from .enums import ToolErrorCode
from .schemas import ToolError

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime


class ToolBase(AvatarRuntimePlugin):
    """Own invocation tasks and resources, never SDK schemas or business descriptions."""

    capabilities: tuple[AvatarCapability, ...] = ()

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
    ) -> None:
        self._runtime = runtime
        self._ready = False
        self._calls: set[asyncio.Task[Any]] = set()
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

    @staticmethod
    def _observe(task: asyncio.Task[Any]) -> None:
        if not task.cancelled():
            task.exception()

    async def on_session_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Tool is closing or closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(
                self._start(), name=f"tool_start:{type(self).__name__}"
            )
            self._start_task.add_done_callback(self._observe)
        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None:
                raise RuntimeError("Tool closed during startup")
            self._ready = True
        except BaseException:
            await self.on_session_stop()
            raise

    async def invoke(self, request: Any) -> Any:
        if not self._ready or self._close_task is not None:
            raise ToolError("Tool is not running", code=ToolErrorCode.UNAVAILABLE)

        task = asyncio.create_task(self._invoke(request), name=f"tool_call:{type(self).__name__}")
        self._calls.add(task)
        task.add_done_callback(self._observe)
        try:
            return await task
        finally:
            self._calls.discard(task)

    async def _close(self) -> None:
        self._ready = False
        start = self._start_task
        if start is not None:
            if not start.done():
                start.cancel()
            await asyncio.gather(start, return_exceptions=True)
        tasks = tuple(self._calls)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._calls.clear()
        await self._stop()

    async def on_session_stop(self) -> None:
        if asyncio.current_task() in self._calls:
            raise RuntimeError("A tool invocation cannot close its owner")
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                self._close(), name=f"tool_close:{type(self).__name__}"
            )
        await wait_for_cleanup(self._close_task)

    @abstractmethod
    async def _start(self) -> None: ...

    @abstractmethod
    async def _invoke(self, request: Any) -> Any: ...

    @abstractmethod
    async def _stop(self) -> None: ...
