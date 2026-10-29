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
import multiprocessing as mp
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.host.execution.manager import ExecutionManager
from alphaavatar.host.processes.supervisor import ProcessSupervisor
from alphaavatar.host.sessions.factory import create_session_backend

from .health import HealthServer

if TYPE_CHECKING:
    from alphaavatar.agents.runtime.inference import InferenceRuntime
    from alphaavatar.host.configs.application import ApplicationConfig

logger = logging.getLogger(__name__)


class AvatarHost:
    """Coordinate application services; backend, execution and process owners stay separate."""

    def __init__(self, config: ApplicationConfig, *, devmode: bool = False) -> None:
        self.config, self._devmode = config, devmode

        self._backend = create_session_backend(config.host.rtc)
        self._supervisor = ProcessSupervisor(
            config.host.processes, application=config.payload, devmode=devmode
        )
        self._manager = ExecutionManager(
            self._supervisor,
            capacity=config.host.processes.capacity,
            policy=config.host.execution,
            admission_ready=self._inference_ready,
        )
        self._health = HealthServer(
            config.host.health, devmode=devmode, ready=lambda: self.ready, status=self.status
        )

        self._inference: InferenceRuntime | None = None

        self._stop = asyncio.Event()
        self._health_start: asyncio.Task[None] | None = None
        self._inference_start: asyncio.Task[None] | None = None
        self._backend_task: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

    @property
    def ready(self) -> bool:
        return self._inference_ready() and self._backend.ready and self._manager.healthy

    @property
    def stop_event(self) -> asyncio.Event:
        return self._stop

    @staticmethod
    def _observe(task: asyncio.Future[Any]) -> None:
        if not task.cancelled():
            task.exception()

    def _inference_ready(self) -> bool:
        return bool(
            self._close_task is None and self._inference is not None and self._inference.is_alive
        )

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "inference_ready": self._inference_ready(),
            "session_backend_ready": self._backend.ready,
            "active_executions": self._manager.active_count,
            "admission_available": self._backend.ready and self._manager.available,
            "recent_executions": [asdict(view) for view in self._manager.snapshot()[-16:]],
            "inference_runners": [asdict(view) for view in self._inference.snapshot()]
            if self._inference is not None
            else [],
            "inference_methods": list(self._inference.methods)
            if self._inference is not None
            else [],
        }

    async def _monitor(self) -> None:
        while True:
            if not self._manager.healthy:
                raise RuntimeError("Execution process supervision failed")

            if not self._inference_ready():
                # Rebuild a failed process without replaying its in-flight work.
                # If reaping or restart fails, fail closed as before.
                if self._inference is None or not await self._inference.recover_failed_runners():
                    raise RuntimeError("Shared inference service failed")
            await asyncio.sleep(self.config.host.inference_check_interval)

    async def _serve(self) -> None:
        from alphaavatar.agents.runtime.inference import (
            InferenceRuntime,
            RunnerLaunch,
            bootstrap_inference_runners,
            prepare_inference_runners,
        )
        from alphaavatar.core.workspace import (
            check_legacy_identity,
            check_workspace_continuity,
            prepare_application,
            prepare_workspace,
        )

        # Workspace
        def activate_paths() -> None:
            check_workspace_continuity(self.config.workspace, self.config.previous_workspace_roots)
            if self.config.workspace == self.config.paths.workspace(self.config.avatar.avatar.id):
                check_legacy_identity(self.config.paths.avatars_dir, self.config.avatar.avatar.id)
            prepare_application(self.config.paths)
            prepare_workspace(self.config.workspace)

        await asyncio.to_thread(activate_paths)

        # Health
        self._health_start = asyncio.create_task(self._health.on_start(), name="host_health_start")
        self._health_start.add_done_callback(self._observe)
        await asyncio.shield(self._health_start)
        logger.info("Host health started port=%d", self._health.port)

        # Inference
        prepare_inference_runners(self.config.avatar)
        self._inference = InferenceRuntime(
            bootstrap_inference_runners(),
            mp_ctx=mp.get_context("spawn"),
            launch=RunnerLaunch(
                str(self.config.workspace.root), str(self.config.paths.cache.models_dir)
            ),
        )
        self._inference_start = asyncio.create_task(
            self._inference.start(), name="host_inference_start"
        )
        self._inference_start.add_done_callback(self._observe)

        await asyncio.shield(self._inference_start)
        if not self._inference_ready():
            raise RuntimeError("Shared inference service did not become ready")

        logger.info(
            "Host inference ready methods=%s health_port=%d",
            self._inference.methods,
            self._health.port,
        )

        # Backend
        self._backend_task = asyncio.create_task(
            self._backend.serve(self._manager, agent_name=self.config.avatar.avatar.name),
            name="host_session_backend",
        )

        self._monitor_task = asyncio.create_task(self._monitor(), name="host_service_monitor")
        for task in (self._backend_task, self._monitor_task):
            task.add_done_callback(self._observe)

        done, _ = await asyncio.wait(
            (self._backend_task, self._monitor_task), return_when=asyncio.FIRST_COMPLETED
        )
        if self._monitor_task in done:
            await self._monitor_task
            raise RuntimeError("Host service monitor ended unexpectedly")

        await self._backend_task

    async def run(self) -> None:
        if self._run_task is not None or self._close_task is not None:
            raise RuntimeError("Avatar Host can only run once")

        self._run_task = asyncio.create_task(self._serve(), name="avatar_host")
        self._run_task.add_done_callback(self._observe)
        stopped = asyncio.create_task(self._stop.wait(), name="host_shutdown_request")
        try:
            done, _ = await asyncio.wait(
                (self._run_task, stopped), return_when=asyncio.FIRST_COMPLETED
            )
            if self._run_task in done:
                await self._run_task
        except BaseException as original:
            try:
                await self.aclose()
            except BaseException as cleanup:
                raise original from cleanup
            raise
        else:
            await self.aclose()
        finally:
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)

    async def _close(self) -> None:
        errors: list[Exception] = []
        self._stop.set()
        self._manager.stop_accepting()

        async def step(operation: Callable[[], Awaitable[None]], label: str) -> None:
            try:
                await operation()
            except asyncio.CancelledError as error:
                failure = RuntimeError(f"{label} cleanup cancelled itself")
                failure.__cause__ = error
                errors.append(failure)
            except Exception as error:
                errors.append(error)

        # Cancel application startup and its monitor, not the backend's final status publisher.
        pending = (self._run_task, self._monitor_task, self._inference_start, self._health_start)
        for task in pending:
            if task is not None and not task.done() and not task.cancelling():
                task.cancel()

        await asyncio.gather(
            *(task for task in pending if task is not None), return_exceptions=True
        )
        await step(self._backend.stop_accepting, "Session admission")
        await step(self._manager.aclose, "Execution manager")
        await step(self._supervisor.aclose, "Process supervisor")
        await step(self._backend.aclose, "Session backend")
        if self._backend_task is not None:
            if not self._backend_task.done():
                self._backend_task.cancel()
            await asyncio.gather(self._backend_task, return_exceptions=True)

        if self._supervisor.all_reaped:
            if self._inference is not None:
                await step(self._inference.close, "Inference service")
        else:
            errors.append(
                RuntimeError(
                    "Execution children remain; shared inference ownership cannot be released"
                )
            )

        await step(self._health.on_stop, "Health server")
        if errors:
            raise ExceptionGroup("Avatar Host shutdown failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="avatar_host_close")
            self._close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._close_task)
