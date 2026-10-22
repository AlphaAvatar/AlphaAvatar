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
from typing import TYPE_CHECKING

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import LifecycleComponent, LifecycleGroup, LifecyclePhase

if TYPE_CHECKING:
    from alphaavatar.agents.avatar import AvatarEngine
    from alphaavatar.agents.runtime import AvatarRuntime


class HostExecution:
    """Own the local Engine and Runtime, never a transport or shared inference process."""

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        engine: AvatarEngine,
        diagnostics: LifecycleComponent | None = None,
    ) -> None:
        self.runtime, self.engine = runtime, engine

        phases = []
        if diagnostics is not None:
            phases.append(LifecyclePhase.create("execution-diagnostics", (diagnostics,)))

        phases.append(LifecyclePhase.create("avatar-engine", (engine,)))
        self._lifecycle = LifecycleGroup(tuple(phases))
        self._close_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Host execution is closing or closed")

        await self._lifecycle.start()
        if self._close_task is not None:
            raise RuntimeError("Host execution closed before readiness")

    async def wait_failed(self) -> None:
        await self.engine.wait_failed()
        raise RuntimeError("Engine failure monitor returned without a failure")

    async def _close(self) -> None:
        errors: list[Exception] = []
        for operation in (self._lifecycle.stop, self.runtime.aclose):
            try:
                await operation()
            except asyncio.CancelledError as error:
                failure = RuntimeError("Execution cleanup cancelled itself")
                failure.__cause__ = error
                errors.append(failure)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Host execution cleanup failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="host_execution_close")
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await wait_for_cleanup(self._close_task)
