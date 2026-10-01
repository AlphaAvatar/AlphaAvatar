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
from collections.abc import Sequence

from alphaavatar.agents.runtime.cleanup import wait_for_cleanup
from alphaavatar.agents.runtime.lifecycle import LifecyclePhase, RuntimePluginLifecycle
from alphaavatar.core.lifecycle import SessionLifecycle


class HostSessionLifecycle:
    """Coordinate the current session-owned execution without closing its shared runtime."""

    def __init__(
        self,
        *,
        engine: SessionLifecycle,
        inputs: Sequence[SessionLifecycle] = (),
        outputs: Sequence[SessionLifecycle] = (),
    ) -> None:
        self._lifecycle = RuntimePluginLifecycle(
            phases=(
                LifecyclePhase.create("rtc-output", outputs),
                LifecyclePhase.create("avatar-engine", (engine,)),
                LifecyclePhase.create("rtc-input", inputs),
            )
        )
        self._start_requested = asyncio.Event()
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Host session is closing or closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(
                self._lifecycle.start(), name="host_session_start"
            )
            self._start_requested.set()
        try:
            await self.wait_ready()
        except asyncio.CancelledError:
            await self.aclose()
            raise

    async def wait_ready(self) -> None:
        await self._start_requested.wait()
        if self._close_task is not None:
            raise RuntimeError("Host session closed before readiness")
        task = self._start_task
        if task is None:
            raise RuntimeError("Host session startup was not scheduled")
        await asyncio.shield(task)
        if self._close_task is not None:
            raise RuntimeError("Host session closed before readiness")

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="host_session_close")
            self._start_requested.set()
        await wait_for_cleanup(self._close_task)

    async def _close(self) -> None:
        task = self._start_task
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._lifecycle.stop()
