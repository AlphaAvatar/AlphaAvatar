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
from dataclasses import replace
from types import MappingProxyType

from alphaavatar.agents.avatar.loop import AvatarLoopBase, LoopDependencies, LoopHandle, LoopRequest
from alphaavatar.core.cleanup import wait_for_cleanup

from .config import RealtimeLoopConfig
from .execution import LoopExecution


class AvatarLoop(AvatarLoopBase):
    """One foreground execution; interrupted executions retain ownership of their cleanup."""

    def __init__(self, config: RealtimeLoopConfig, *, dependencies: LoopDependencies) -> None:
        self._config = config.model_copy(deep=True)
        self._dependencies = replace(
            dependencies, tool_policies=MappingProxyType(dict(dependencies.tool_policies))
        )
        self._runs: dict[str, LoopExecution] = {}
        self._current: LoopExecution | None = None
        self._unsafe_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None

    def interrupt(self, *, run_id: str | None = None, reason: str = "interrupted") -> None:
        execution = self._runs.get(run_id) if run_id is not None else self._current
        if execution is not None:
            execution.cancel(reason=reason)

    async def submit(self, request: LoopRequest) -> LoopHandle:
        if self._close_task is not None:
            raise RuntimeError("Avatar loop is closing or closed")

        if not isinstance(request, LoopRequest):
            raise TypeError("Expected LoopRequest")

        if len(self._runs) >= self._config.max_retiring_runs + 1:
            raise RuntimeError("Previous execution cleanup is still pending")

        if self._current is not None and not self._current.task.done():
            if self._current.identity.turn_id == request.turn_id:
                raise ValueError("This turn already has an active execution")

        # Validate the next execution's dependencies before cancelling the current one.
        request = replace(request, metadata=MappingProxyType(dict(request.metadata)))
        execution = LoopExecution(
            request,
            self._config,
            self._dependencies,
            self._unsafe_lock,
            is_current=lambda identity: self._current is not None
            and self._current.identity.run_id == identity,
        )
        if self._current is not None:
            self._current.cancel(reason="superseded")
        self._current = execution
        self._runs[execution.identity.run_id] = execution

        def finished(task: asyncio.Task) -> None:
            self._runs.pop(execution.identity.run_id, None)
            if self._current is execution:
                self._current = None

        execution.task.add_done_callback(finished)
        return execution

    async def _close(self) -> None:
        runs = tuple(self._runs.values())
        for run in runs:
            run.cancel(reason="loop_closed")
        results = await asyncio.gather(*(run.aclose() for run in runs), return_exceptions=True)
        errors = [result for result in results if isinstance(result, Exception)]
        self._runs.clear()
        self._current = None
        if errors:
            raise ExceptionGroup("Avatar loop cleanup failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="avatar_loop_close")
        await wait_for_cleanup(self._close_task)
