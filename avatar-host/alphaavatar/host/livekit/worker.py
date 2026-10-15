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
from dataclasses import replace
from math import isfinite
from typing import Any, Literal

from aiohttp import web
from livekit.agents.worker import AgentServer, ServerEnvOption, WorkerInfo

from alphaavatar.agents.runtime.inference import InferenceRuntime, bootstrap_inference_runners
from alphaavatar.core.cleanup import wait_for_cleanup

logger = logging.getLogger(__name__)
DEFAULT_HEALTH_PORT = ServerEnvOption(dev_default=0, prod_default=8081)


class LiveKitWorker(AgentServer):
    """SDK dispatch boundary; Host owns inference, not a copy of SDK process internals."""

    def __init__(
        self,
        *,
        host: str = "",
        port: int | ServerEnvOption[int] = DEFAULT_HEALTH_PORT,
        multiprocessing_context: Literal["spawn"] = "spawn",
        inference_check_interval: float = 0.5,
        **options: Any,
    ) -> None:
        # Each worker's children must inherit its own final endpoint, not an old forkserver's.
        if multiprocessing_context != "spawn":
            raise ValueError("LiveKitWorker requires the spawn multiprocessing context")
        if (
            type(inference_check_interval) not in (int, float)
            or not isfinite(inference_check_interval)
            or inference_check_interval <= 0
        ):
            raise ValueError("inference_check_interval must be positive and finite")
        for devmode in (False, True):
            value = ServerEnvOption.getvalue(port, devmode)
            if type(value) is not int or not 0 <= value <= 65535:
                raise ValueError("Worker health port must be an integer in 0..65535")
        self._host_bind, self._host_port = host or "0.0.0.0", port
        self._host_http_port = 0
        self._host_http: web.AppRunner | None = None
        self._host_http_start: asyncio.Task[None] | None = None
        self._host_sdk_started = False
        # Keep SDK's implementation-detail HTTP listener private; Host exposes readiness.
        super().__init__(
            host="127.0.0.1", port=0, multiprocessing_context=multiprocessing_context, **options
        )
        self.on("worker_started", self._sdk_started)
        self._host_context = mp.get_context(multiprocessing_context)
        self._inference_check_interval = float(inference_check_interval)
        self._host_inference: InferenceRuntime | None = None
        self._host_inference_healthy = False
        self._host_start_task: asyncio.Task[None] | None = None
        self._host_run_task: asyncio.Task[None] | None = None
        self._host_monitor_task: asyncio.Task[None] | None = None
        self._host_sdk_task: asyncio.Task[None] | None = None
        self._host_close_task: asyncio.Task[None] | None = None

    def _sdk_started(self) -> None:
        self._host_sdk_started = True

    @property
    def worker_info(self) -> WorkerInfo:
        return replace(super().worker_info, http_port=self._host_http_port)

    @property
    def inference_ready(self) -> bool:
        # SDK load callbacks may run in a thread; do not poll process handles there.
        return self._host_close_task is None and self._host_inference_healthy

    def _refresh_inference(self) -> bool:
        self._host_inference_healthy = bool(
            self._host_inference is not None and self._host_inference.is_alive
        )
        return self.inference_ready

    @property
    def ready(self) -> bool:
        return bool(
            self._refresh_inference()
            and self._host_sdk_started
            and self._host_sdk_task is not None
            and not self._host_sdk_task.done()
        )

    async def _health(self, request: web.Request) -> web.Response:
        ready = self.ready
        return web.Response(text="OK" if ready else "Not ready", status=200 if ready else 503)

    async def _status(self, request: web.Request) -> web.Response:
        ready = self.ready
        methods = list(self._host_inference.methods) if self._host_inference else []
        return web.json_response(
            {
                "ready": ready,
                "inference_ready": self.inference_ready,
                "active_jobs": len(self.active_jobs) if ready else None,
                "inference_methods": methods,
            }
        )

    async def _start_health(self, devmode: bool) -> None:
        app = web.Application()
        app.add_routes([web.get("/", self._health), web.get("/worker", self._status)])
        self._host_http = web.AppRunner(app, access_log=None, shutdown_timeout=5.0)
        await self._host_http.setup()
        port = ServerEnvOption.getvalue(self._host_port, devmode)
        await web.TCPSite(self._host_http, self._host_bind, port).start()
        self._host_http_port = self._host_http.addresses[0][1]

    @staticmethod
    def _observe(task: asyncio.Future[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _monitor_inference(self) -> None:
        while self._host_close_task is None:
            if not self._refresh_inference():
                raise RuntimeError("Inference service failed; the worker cannot accept more jobs")
            await asyncio.sleep(self._inference_check_interval)

    async def _serve(self, *, devmode: bool, unregistered: bool) -> None:
        if self._host_close_task is not None:
            return
        self._host_http_start = asyncio.create_task(
            self._start_health(devmode), name="host_worker_health_start"
        )
        self._host_http_start.add_done_callback(self._observe)
        await asyncio.shield(self._host_http_start)
        if self._host_close_task is not None:
            return
        self._host_inference = InferenceRuntime(
            bootstrap_inference_runners(), mp_ctx=self._host_context
        )
        self._host_start_task = asyncio.create_task(
            self._host_inference.start(), name="host_inference_start"
        )
        self._host_start_task.add_done_callback(self._observe)
        try:
            # Initialize selected models and export the endpoint before SDK job processes exist.
            await asyncio.shield(self._host_start_task)
            if self._host_close_task is not None:
                return
            if not self._refresh_inference():
                raise RuntimeError("Inference service did not become ready")
            logger.info("Host inference ready runners=%s", self._host_inference.methods)
            self._host_sdk_task = asyncio.create_task(
                super().run(devmode=devmode, unregistered=unregistered), name="host_sdk_dispatch"
            )
            self._host_sdk_task.add_done_callback(self._observe)
            self._host_monitor_task = asyncio.create_task(
                self._monitor_inference(), name="host_inference_monitor"
            )
            self._host_monitor_task.add_done_callback(self._observe)
            done, _ = await asyncio.wait(
                (self._host_sdk_task, self._host_monitor_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self._host_monitor_task in done:
                await self._host_monitor_task
                if self._host_close_task is None:
                    raise RuntimeError("Inference monitor stopped unexpectedly")
            await self._host_sdk_task
        except asyncio.CancelledError as error:
            if self._host_close_task is None:
                raise RuntimeError("Host worker task cancelled unexpectedly") from error

    async def run(self, *, devmode: bool = False, unregistered: bool = False) -> None:
        if self._host_close_task is not None:
            raise RuntimeError("LiveKit worker is closing or closed")
        if self._host_run_task is not None:
            raise RuntimeError("LiveKit worker can only run once")
        self._host_run_task = asyncio.create_task(
            self._serve(devmode=devmode, unregistered=unregistered), name="host_worker_run"
        )
        self._host_run_task.add_done_callback(self._observe)
        try:
            await asyncio.shield(self._host_run_task)
        except BaseException as original:
            try:
                await self.aclose()
            except BaseException as cleanup:
                raise original from cleanup
            raise
        else:
            await self.aclose()

    @staticmethod
    async def _close_step(
        operation: Callable[[], Awaitable[None]], label: str, errors: list[Exception]
    ) -> None:
        try:
            await operation()
        except asyncio.CancelledError as error:
            failure = RuntimeError(f"{label} cleanup cancelled unexpectedly")
            failure.__cause__ = error
            errors.append(failure)
        except Exception as error:
            errors.append(error)

    async def _close_host(self) -> None:
        errors: list[Exception] = []
        start, monitor = self._host_start_task, self._host_monitor_task
        for task in (start, monitor):
            if task is not None and not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(
            *(task for task in (start, monitor) if task is not None), return_exceptions=True
        )

        # Do not cancel SDK startup: its public close owns the job pool and startup lock.
        # All jobs must settle their consumers before the shared inference endpoint is removed.
        if self._host_sdk_task is not None:
            await self._close_step(super().aclose, "LiveKit dispatch", errors)
            if not self._host_sdk_task.done():
                self._host_sdk_task.cancel()
            await asyncio.gather(self._host_sdk_task, return_exceptions=True)
        if self._host_inference is not None:
            await self._close_step(self._host_inference.close, "Inference service", errors)
        if self._host_run_task is not None:
            await asyncio.gather(self._host_run_task, return_exceptions=True)
        if self._host_http_start is not None:
            await asyncio.gather(self._host_http_start, return_exceptions=True)
        if self._host_http is not None:
            await self._close_step(self._host_http.cleanup, "Host health server", errors)
        if errors:
            raise ExceptionGroup("Host worker shutdown failed", errors)

    async def aclose(self) -> None:
        if self._host_close_task is None:
            self._host_close_task = asyncio.create_task(
                self._close_host(), name="host_worker_close"
            )
            self._host_close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._host_close_task)
