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
from typing import TYPE_CHECKING

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import LifecycleComponent, LifecycleGroup, LifecyclePhase

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime


class HostExecution:
    """Own an execution and its runtime; transport disconnection is the Host's policy."""

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        engine: LifecycleComponent,
        inputs: Sequence[LifecycleComponent] = (),
        outputs: Sequence[LifecycleComponent] = (),
        presentations: Sequence[LifecycleComponent] = (),
    ) -> None:
        self._runtime = runtime
        self._lifecycle = LifecycleGroup(
            phases=(
                LifecyclePhase.create("presentation", presentations),
                LifecyclePhase.create("rtc-output", outputs),
                LifecyclePhase.create("avatar-engine", (engine,)),
                LifecyclePhase.create("rtc-input", inputs),
            )
        )
        self._close_task: asyncio.Task[None] | None = None

    @staticmethod
    def _observe(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Host execution is closing or closed")
        try:
            await self._lifecycle.start()
            if self._close_task is not None:
                raise RuntimeError("Host execution closed before readiness")
        except BaseException as original:
            try:
                await self.aclose()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def wait_ready(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Host execution is closing or closed")
        await self._lifecycle.wait_ready()
        if self._close_task is not None:
            raise RuntimeError("Host execution closed before readiness")

    async def _close(self) -> None:
        errors: list[Exception] = []
        for operation in (self._lifecycle.stop, self._runtime.aclose):
            try:
                await operation()
            except asyncio.CancelledError as error:
                failure = RuntimeError("Host execution cleanup cancelled itself")
                failure.__cause__ = error
                errors.append(failure)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Host execution cleanup failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="host_execution_close")
            self._close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._close_task)
