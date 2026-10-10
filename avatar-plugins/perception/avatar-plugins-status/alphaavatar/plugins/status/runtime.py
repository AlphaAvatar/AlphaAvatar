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

from alphaavatar.agents.status import StatusBase, StatusProcessorBase
from alphaavatar.core.cleanup import wait_for_cleanup

from .config import StatusRuntimeConfig
from .processors.activity import ActivityProcessor
from .processors.narration import NarrationProcessor
from .processors.presentation import PresentationProcessor
from .state import StatusState

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime


class StatusRuntime(StatusBase):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        config: StatusRuntimeConfig,
        enabled: bool = True,
    ) -> None:
        state = StatusState(
            max_pending=config.activity.max_pending,
            max_runs=config.activity.max_runs,
        )
        self._processors: tuple[StatusProcessorBase, ...] = (
            (
                NarrationProcessor(runtime, state, config.narration),
                PresentationProcessor(runtime, state, config.presentation),
                ActivityProcessor(runtime, state, config.activity),
            )
            if enabled
            else ()
        )

        self._started: list[StatusProcessorBase] = []
        self._start_task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None

    async def _start(self) -> None:
        for processor in self._processors:
            # Own the partially started processor before its first suspension.
            self._started.append(processor)
            await processor.start()
        if self._close_task is not None:
            raise asyncio.CancelledError

    async def on_session_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Status runtime is closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="status:start")
        try:
            await asyncio.shield(self._start_task)
        except BaseException as original:
            try:
                await self.on_session_stop()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def _close(self) -> None:
        if self._start_task is not None:
            if not self._start_task.done():
                self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        errors = []
        for processor in reversed(self._started):
            try:
                await processor.stop()
            except asyncio.CancelledError as exc:
                error = RuntimeError("Status processor cleanup cancelled itself")
                error.__cause__ = exc
                errors.append(error)
            except Exception as exc:
                errors.append(exc)
        self._started.clear()
        if errors:
            raise ExceptionGroup("Status cleanup failed", errors)

    async def on_session_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="status:close")
        await wait_for_cleanup(self._close_task)
