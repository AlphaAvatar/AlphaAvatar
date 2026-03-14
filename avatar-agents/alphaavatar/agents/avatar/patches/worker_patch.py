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
import asyncio
import json
import math
import os
from typing import Any

import aiohttp
from aiohttp import web
from livekit import api, rtc
from livekit.agents import Plugin, ipc, telemetry, utils, version, worker as livekit_worker
from livekit.agents.inference_runner import _InferenceRunner
from livekit.protocol import agent

from alphaavatar.agents.log import logger


class AvatarServer(livekit_worker.AgentServer):
    async def run(self, *, devmode: bool = False, unregistered: bool = False) -> None:
        """This method starts the worker's internal event loop, initializes any required
        executors, HTTP servers, and process pools, and optionally registers the worker
        with the LiveKit server.

        Args:
            devmode (bool, optional):
                If True, the worker runs in development mode.
                This affects certain environment-dependent defaults, such as the
                number of idle processes, logging verbosity, and load thresholds,
                making it easier to test and debug without production constraints.

            unregistered (bool, optional):
                If True, the worker will start without registering itself with the
                LiveKit server.
                This allows the worker to operate in a partially connected state—
                capable of using other providers or local processing—but invisible
                to the central LiveKit job dispatcher.
                Useful for local testing, isolated jobs, or running without being
                assigned new jobs.
        """
        async with self._lock:
            if not self._closed:
                raise Exception("worker is already running")

            if self._entrypoint_fnc is None:
                raise RuntimeError(
                    "No RTC session entrypoint has been registered.\n"
                    "Define one using the @server.rtc_session() decorator, for example:\n"
                    '    @server.rtc_session(agent_name="my_agent")\n'
                    "    async def my_agent(ctx: JobContext):\n"
                    "        ...\n"
                )

            if self._request_fnc is None:
                self._request_fnc = livekit_worker._default_request_fnc

            if self._setup_fnc is None:
                self._setup_fnc = livekit_worker._default_setup_fnc

            if self._load_fnc is None:
                self._load_fnc = livekit_worker._DefaultLoadCalc.get_load

            if self.worker_info.cloud_agents:
                if self._load_fnc != livekit_worker._DefaultLoadCalc.get_load:
                    logger.warning(
                        "custom load_fnc is not supported when hosting on Cloud, reverting to default"
                    )
                    self._load_fnc = livekit_worker._DefaultLoadCalc.get_load
                if self._load_threshold != livekit_worker._default_load_threshold:
                    logger.warning(
                        "custom load_threshold is not supported when hosting on Cloud, reverting to default"
                    )
                    self._load_threshold = livekit_worker._default_load_threshold

            self._loop = asyncio.get_event_loop()
            self._devmode = devmode
            self._job_lifecycle_tasks = set[asyncio.Task[Any]]()
            self._pending_assignments: dict[str, asyncio.Future[agent.JobAssignment]] = {}
            self._close_future: asyncio.Future[None] | None = None
            self._msg_chan = utils.aio.Chan[agent.WorkerMessage](128, loop=self._loop)

            self._inference_executor: ipc.inference_proc_executor.InferenceProcExecutor | None = (
                None
            )
            if len(_InferenceRunner.registered_runners) > 0:
                self._inference_executor = ipc.inference_proc_executor.InferenceProcExecutor(
                    runners=_InferenceRunner.registered_runners,
                    initialize_timeout=5 * 60,
                    close_timeout=5,
                    memory_warn_mb=self._job_memory_warn_mb
                    // 2,  # Patch: inference executor gets half the memory limit of a regular job
                    memory_limit_mb=0,  # no limit
                    ping_interval=5,
                    ping_timeout=60,
                    high_ping_threshold=2.5,
                    mp_ctx=self._mp_ctx,
                    loop=self._loop,
                    http_proxy=self._http_proxy or None,
                )

            self._proc_pool = ipc.proc_pool.ProcPool(
                initialize_process_fnc=self._setup_fnc,
                job_entrypoint_fnc=self._entrypoint_fnc,
                session_end_fnc=self._session_end_fnc,
                num_idle_processes=livekit_worker.ServerEnvOption.getvalue(
                    self._num_idle_processes, devmode
                ),
                loop=self._loop,
                job_executor_type=self._job_executor_type,
                inference_executor=self._inference_executor,
                mp_ctx=self._mp_ctx,
                initialize_timeout=self._initialize_process_timeout,
                close_timeout=self._shutdown_process_timeout,
                memory_warn_mb=self._job_memory_warn_mb,
                memory_limit_mb=self._job_memory_limit_mb,
                http_proxy=self._http_proxy or None,
            )

            self._previous_status = agent.WorkerStatus.WS_AVAILABLE

            self._api: api.LiveKitAPI | None = None
            self._http_session: aiohttp.ClientSession | None = None
            self._http_server = utils.http_server.HttpServer(
                self._host, livekit_worker.ServerEnvOption.getvalue(self._port, devmode)
            )
            self._worker_load: float = 0.0
            self._reserved_slots: int = 0  # jobs we said "available" to but not yet launched

            async def health_check(_: Any) -> web.Response:
                if self._inference_executor and not self._inference_executor.is_alive():
                    return web.Response(status=503, text="inference process not running")

                if self._connection_failed:
                    return web.Response(status=503, text="failed to connect to livekit")

                return web.Response(text="OK")

            async def worker(_: Any) -> web.Response:
                body = json.dumps(
                    {
                        "agent_name": self._agent_name,
                        "worker_type": agent.JobType.Name(self._server_type.value),
                        "worker_load": self._worker_load,
                        "active_jobs": len(self.active_jobs),
                        "sdk_version": version.__version__,
                        "project_type": "python",
                    }
                )
                return web.Response(body=body, content_type="application/json")

            self._http_server.app.add_routes([web.get("/", health_check)])
            self._http_server.app.add_routes([web.get("/worker", worker)])

            self._conn_task: asyncio.Task[None] | None = None
            self._load_task: asyncio.Task[None] | None = None

            if not self._ws_url:
                raise ValueError("ws_url is required, or set LIVEKIT_URL environment variable")

            if not self._api_key:
                raise ValueError("api_key is required, or set LIVEKIT_API_KEY environment variable")

            if not self._api_secret:
                raise ValueError(
                    "api_secret is required, or set LIVEKIT_API_SECRET environment variable"
                )

            self._prometheus_server: telemetry.http_server.HttpServer | None = None
            if self._prometheus_port is not None:
                self._prometheus_server = telemetry.http_server.HttpServer(
                    self._host, self._prometheus_port
                )

            if self._prometheus_multiproc_dir:
                os.environ["PROMETHEUS_MULTIPROC_DIR"] = self._prometheus_multiproc_dir
            elif "PROMETHEUS_MULTIPROC_DIR" in os.environ:
                self._prometheus_multiproc_dir = os.environ["PROMETHEUS_MULTIPROC_DIR"]

            if self._prometheus_multiproc_dir:
                os.makedirs(self._prometheus_multiproc_dir, exist_ok=True)

            if self._prometheus_multiproc_dir and os.path.exists(self._prometheus_multiproc_dir):
                logger.debug(
                    "cleaning prometheus multiprocess directory",
                    extra={"path": self._prometheus_multiproc_dir},
                )
                for filename in os.listdir(self._prometheus_multiproc_dir):
                    file_path = os.path.join(self._prometheus_multiproc_dir, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.unlink(file_path)
                    except Exception as e:
                        logger.warning(f"failed to remove {file_path}", exc_info=e)

            os.environ["LIVEKIT_URL"] = self._ws_url
            os.environ["LIVEKIT_API_KEY"] = self._api_key
            os.environ["LIVEKIT_API_SECRET"] = self._api_secret

            logger.info(
                "starting worker",
                extra={"version": version.__version__, "rtc-version": rtc.__version__},
            )

            if self._mp_ctx_str == "forkserver":
                plugin_packages = [p.package for p in Plugin.registered_plugins] + ["av"]
                logger.info("preloading plugins", extra={"packages": plugin_packages})
                self._mp_ctx.set_forkserver_preload(plugin_packages)

            if self._inference_executor is not None:
                logger.info("starting inference executor")
                await self._inference_executor.start()
                await self._inference_executor.initialize()

            self._closed = False

            def _update_job_status(proc: ipc.job_executor.JobExecutor) -> None:
                t = self._loop.create_task(self._update_job_status(proc))
                self._job_lifecycle_tasks.add(t)
                t.add_done_callback(self._job_lifecycle_tasks.discard)

            await self._http_server.start()
            logger.info(
                f"HTTP server listening on {self._http_server.host}:{self._http_server.port}"
            )

            if self._prometheus_server:
                await self._prometheus_server.start()
                logger.info(
                    "Prometheus metrics exposed at http://%s:%s/metrics",
                    self._prometheus_server.host,
                    self._prometheus_server.port,
                )

            self._proc_pool.on("process_started", _update_job_status)
            self._proc_pool.on("process_closed", _update_job_status)
            self._proc_pool.on("process_job_launched", _update_job_status)
            await self._proc_pool.start()

            self._http_session = aiohttp.ClientSession(proxy=self._http_proxy or None)
            self._api = api.LiveKitAPI(
                self._ws_url, self._api_key, self._api_secret, session=self._http_session
            )
            self._close_future = asyncio.Future(loop=self._loop)

            @utils.log_exceptions(logger=logger)
            async def _load_task() -> None:
                """periodically check load"""

                interval = utils.aio.interval(livekit_worker.UPDATE_LOAD_INTERVAL)
                while True:
                    await interval.tick()

                    self._worker_load = await self._invoke_load_fnc()

                    telemetry.metrics._update_worker_load(self._worker_load)
                    if self._prometheus_multiproc_dir:
                        await asyncio.get_event_loop().run_in_executor(
                            None, telemetry.metrics._update_child_proc_count
                        )

                    load_threshold = livekit_worker.ServerEnvOption.getvalue(
                        self._load_threshold, devmode
                    )
                    default_num_idle_processes = livekit_worker.ServerEnvOption.getvalue(
                        self._num_idle_processes, devmode
                    )

                    if not math.isinf(load_threshold):
                        active_jobs = len(self.active_jobs)
                        if active_jobs > 0:
                            job_load = self._worker_load / len(self.active_jobs)
                            if job_load > 0.0:
                                available_load = max(load_threshold - self._worker_load, 0.0)
                                available_job = min(
                                    math.ceil(available_load / job_load), default_num_idle_processes
                                )
                                self._proc_pool.set_target_idle_processes(available_job)
                        else:
                            self._proc_pool.set_target_idle_processes(default_num_idle_processes)

            tasks = []
            self._load_task = asyncio.create_task(_load_task(), name="load_task")
            tasks.append(self._load_task)

            if not unregistered:
                self._conn_task = asyncio.create_task(
                    self._connection_task(), name="worker_conn_task"
                )
                tasks.append(self._conn_task)

            self.emit("worker_started")

        await self._close_future
