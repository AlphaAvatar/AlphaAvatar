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
from alphaavatar.host.sessions.schemas import SessionRequest

from .config import ProcessConfig
from .group import ProcessGroup
from .process import ExecutionProcess


class ProcessSupervisor:
    """Execution children only; InferenceRuntime remains the sole owner of runner processes."""

    def __init__(self, config: ProcessConfig, *, application: str, devmode: bool = False) -> None:
        ProcessGroup.require_supported()
        self._config, self._application, self._devmode = config, application, devmode

        self._processes: dict[str, ExecutionProcess] = {}
        self._close_task: asyncio.Task[None] | None = None

    @property
    def all_reaped(self) -> bool:
        return all(process.reaped for process in self._processes.values())

    def create(self, execution_id: str, request: SessionRequest) -> ExecutionProcess:
        if self._close_task is not None or execution_id in self._processes:
            raise RuntimeError("Execution process cannot be created")

        if len(self._processes) >= self._config.capacity:
            raise RuntimeError("Execution process capacity exhausted")

        process = ExecutionProcess(
            execution_id=execution_id,
            application=self._application,
            request=request,
            config=self._config,
            devmode=self._devmode,
        )
        self._processes[execution_id] = process
        return process

    async def release(self, process: ExecutionProcess) -> None:
        if self._processes.get(process.execution_id) is not process:
            return

        await process.on_stop()
        if not process.reaped:
            raise RuntimeError("Execution process was not reaped")
        self._processes.pop(process.execution_id, None)

    async def _close(self) -> None:
        processes = tuple(self._processes.values())
        results = await asyncio.gather(
            *(self.release(process) for process in processes), return_exceptions=True
        )
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise ExceptionGroup("Execution process shutdown failed", errors)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="process_supervisor_close")
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await wait_for_cleanup(self._close_task)
