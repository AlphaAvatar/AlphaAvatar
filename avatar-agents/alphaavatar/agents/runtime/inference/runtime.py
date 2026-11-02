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
import os
import shutil
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from multiprocessing.context import BaseContext
from typing import TYPE_CHECKING

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.ipc import private_socket_path

from .bootstrap import check_inference_config
from .pool import RunnerPool
from .process import RunnerProcess
from .protocol import (
    CLOSE,
    CONNECT,
    INFERENCE_ENDPOINT_ENV,
    REQUEST,
    RESULT,
    RESULT_NONE,
    RUN_ERROR,
    close_writer,
    positive_limit,
    positive_timeout,
    read_frame,
    service_ready,
    validate_method,
    write_frame,
)
from .runner import InferenceRunner, RunnerLaunch
from .schemas import InferenceRunnerStatus

if TYPE_CHECKING:
    from alphaavatar.agents.configs.runtime_config import InferenceConfig

logger = logging.getLogger(__name__)


class InferenceRuntime:
    """Own one local endpoint and, per method, a bounded pool of serial spawned runners."""

    def __init__(
        self,
        runners: dict[str, type[InferenceRunner]],
        *,
        mp_ctx: BaseContext | None = None,
        launch: RunnerLaunch | None = None,
        config: InferenceConfig | None = None,
        max_clients: int = 256,
        handshake_timeout: float = 10,
    ) -> None:
        if config is None:
            # The Host passes the accepted runtime.inference; defaults serve direct use.
            from alphaavatar.agents.configs.runtime_config import InferenceConfig

            config = InferenceConfig()
        self._launch, self._config = launch, config
        self._runner_classes = dict(runners)
        for method, runner in self._runner_classes.items():
            validate_method(method)
            if not isinstance(runner, type) or not issubclass(runner, InferenceRunner):
                raise TypeError("Inference plans require InferenceRunner classes")
            if runner.INFERENCE_METHOD != method:
                raise ValueError("Inference plan method does not match its runner")
        check_inference_config(self._runner_classes, config)

        self._mp_ctx = mp_ctx or mp.get_context("spawn")
        if self._mp_ctx.get_start_method() == "fork":
            raise ValueError("Inference processes require spawn or forkserver, not fork")

        self._handshake_timeout = positive_timeout(handshake_timeout, "handshake_timeout")
        self._max_clients = positive_limit(max_clients, "max_clients")
        self._restart_history: dict[str, deque[float]] = {
            method: deque() for method in self._runner_classes
        }
        self._recovery_lock = asyncio.Lock()
        self._pools = {
            method: RunnerPool(method, config.workers(method), max_pending=config.max_pending)
            for method in self._runner_classes
        }
        self._startup = {
            method: InferenceRunnerStatus(method=method) for method in self._runner_classes
        }
        self._startup_started: dict[str, float] = {}
        self._server: asyncio.Server | None = None
        self._endpoint: str | None = None
        self._socket_dir: str | None = None
        self._client_tasks: set[asyncio.Task[None]] = set()
        self._client_writers: set[asyncio.StreamWriter] = set()
        self._start_task: asyncio.Task[None] | None = None
        self._directory_task: asyncio.Task[tuple[str, str]] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._started = False
        self._client_error: Exception | None = None

    @property
    def methods(self) -> tuple[str, ...]:
        return tuple(self._runner_classes)

    @property
    def endpoint(self) -> str:
        if self._endpoint is None or not self._started or self._close_task is not None:
            raise RuntimeError("Inference runtime is not ready")
        return self._endpoint

    @property
    def _serving(self) -> bool:
        # Admission is per method; one failed runner must not refuse its healthy peers.
        return bool(
            self._started
            and self._close_task is None
            and self._server is not None
            and self._server.is_serving()
        )

    @property
    def is_alive(self) -> bool:
        """Overall health for supervision and recovery, not request admission."""
        return self._serving and all(
            pool.ready_workers == len(pool.slots) for pool in self._pools.values()
        )

    def snapshot(self) -> tuple[InferenceRunnerStatus, ...]:
        """Read startup facts, readiness and counters without model or request data."""
        now = time.monotonic()
        views = []
        for method, status in self._startup.items():
            pool = self._pools[method]
            ready = 0 if self._close_task is not None else pool.ready_workers
            elapsed = status.startup_elapsed_seconds
            if status.startup_state == "initializing":
                elapsed = max(0.0, now - self._startup_started[method])
            views.append(
                replace(
                    status,
                    ready=ready == len(pool.slots),
                    startup_elapsed_seconds=elapsed,
                    workers=len(pool.slots),
                    ready_workers=ready,
                    executing=pool.executing,
                    waiting=pool.waiting,
                    rejected=pool.rejected,
                    queue_timeouts=pool.queue_timeouts,
                    execution_timeouts=pool.execution_timeouts,
                    restarts=pool.restarts,
                )
            )
        return tuple(views)

    def _process(self, method: str) -> RunnerProcess:
        config = self._config
        return RunnerProcess(
            self._runner_classes[method],
            mp_ctx=self._mp_ctx,
            initialize_timeout=config.initialize_timeout,
            request_timeout=config.request_timeout,
            close_timeout=config.close_timeout,
            max_pending=1,  # The pool queues; a worker never holds a second request.
            launch=self._launch,
            on_settled=self._pools[method].wake,
        )

    async def _initialize_runner(self, method: str, slots: Sequence[int], index: int) -> None:
        pool = self._pools[method]
        started = self._startup_started[method] = time.monotonic()
        self._startup[method] = InferenceRunnerStatus(method=method, startup_state="initializing")
        logger.info(
            "Inference runner initializing method=%r workers=%d/%d progress=%d/%d",
            method,
            len(slots),
            len(pool.slots),
            index,
            len(self._runner_classes),
        )
        try:
            for slot in slots:
                # Own partial initialization before the first await; unready workers get no work.
                worker = pool.slots[slot] = self._process(method)
                await worker.start()
        except BaseException as error:
            cancelled = isinstance(error, asyncio.CancelledError)
            elapsed = time.monotonic() - started
            self._startup[method] = InferenceRunnerStatus(
                method=method,
                startup_state="cancelled" if cancelled else "failed",
                startup_elapsed_seconds=elapsed,
                error_type=type(error).__name__,
            )
            logger.log(
                logging.INFO if cancelled else logging.ERROR,
                "Inference runner startup state=%s method=%r elapsed=%.3fs error_type=%s",
                self._startup[method].startup_state,
                method,
                elapsed,
                type(error).__name__,
            )
            raise
        self._startup[method] = InferenceRunnerStatus(
            method=method, startup_state="ready", startup_elapsed_seconds=time.monotonic() - started
        )
        pool.wake()
        logger.info(
            "Inference runner ready method=%r elapsed=%.3fs progress=%d/%d",
            method,
            self._startup[method].startup_elapsed_seconds,
            index,
            len(self._runner_classes),
        )

    async def _close_runner(self, method: str, runner: RunnerProcess) -> None:
        started = time.monotonic()
        logger.info("Inference runner closing method=%r", method)
        try:
            await runner.close()
        except BaseException as error:
            logger.error(
                "Inference runner close failed method=%r elapsed=%.3fs error_type=%s",
                method,
                time.monotonic() - started,
                type(error).__name__,
            )
            raise
        logger.info(
            "Inference runner closed method=%r elapsed=%.3fs", method, time.monotonic() - started
        )

    @staticmethod
    def _observe(task: asyncio.Future) -> None:
        if not task.cancelled():
            task.exception()

    async def _listen(self) -> None:
        self._server = await asyncio.start_unix_server(
            self._accept_client, path=self._endpoint, start_serving=False
        )

    async def _start(self) -> None:
        if os.environ.get(INFERENCE_ENDPOINT_ENV):
            raise RuntimeError("An inference endpoint is already configured in this process")

        self._directory_task = asyncio.create_task(
            asyncio.to_thread(private_socket_path, "alphaavatar-inference-", "runtime.sock")
        )
        self._directory_task.add_done_callback(self._observe)
        self._socket_dir, self._endpoint = await asyncio.shield(self._directory_task)
        self._listen_task = asyncio.create_task(self._listen())
        self._listen_task.add_done_callback(self._observe)
        await asyncio.shield(self._listen_task)

        # Export before the first forkserver starts so job processes inherit the final path.
        if os.environ.get(INFERENCE_ENDPOINT_ENV):
            raise RuntimeError("Another inference runtime acquired the process endpoint")

        os.environ[INFERENCE_ENDPOINT_ENV] = self._endpoint
        for index, (method, pool) in enumerate(self._pools.items(), start=1):
            await self._initialize_runner(method, range(len(pool.slots)), index)

        if self._close_task is not None:
            raise RuntimeError("Inference runtime closed during initialization")
        await self._server.start_serving()
        self._started = True

    async def start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Inference runtime is closing or closed")

        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="inference_runtime_start")
            self._start_task.add_done_callback(self._observe)

        try:
            await asyncio.shield(self._start_task)
            if not self.is_alive:
                raise RuntimeError("Inference runtime failed to become ready")
        except BaseException as original:
            try:
                await self.close()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    def _accept_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if not self._serving or len(self._client_tasks) >= self._max_clients:
            writer.transport.abort()
            return

        self._client_writers.add(writer)
        task = asyncio.create_task(self._handle_client(reader, writer), name="inference_client")
        self._client_tasks.add(task)
        task.add_done_callback(self._client_tasks.discard)
        task.add_done_callback(self._observe_client)

    def _observe_client(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            if self._close_task is None:
                self._client_error = self._client_error or RuntimeError(
                    "Inference client handler cancelled unexpectedly"
                )
        elif (error := task.exception()) is not None:
            self._client_error = self._client_error or error

    async def _respond(self, method: str, data: bytes) -> bytes:
        config = self._config
        try:
            # The pool resolves workers per request: a retired process never serves again.
            result = await self._pools[method].run(
                data, queue_timeout=config.queue_timeout, timeout=config.request_timeout
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Results are never retried. The caller learns failure, not a guessed outcome.
            return RUN_ERROR + str(error).encode("utf-8", errors="replace")[-16384:]
        return RESULT_NONE if result is None else RESULT + result

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        config = self._config
        reading: asyncio.Task[bytes] | None = None
        work: asyncio.Task[bytes] | None = None
        try:
            async with asyncio.timeout(self._handshake_timeout):
                message = await read_frame(reader)
                if message[:1] != CONNECT:
                    raise ValueError("Invalid inference handshake")
                method = message[1:].decode("utf-8")
                validate_method(method)
                if method not in self._runner_classes:
                    await write_frame(writer, RUN_ERROR + b"Inference method is not registered")
                    return
                await write_frame(
                    writer,
                    service_ready(
                        queue=config.queue_timeout,
                        execution=config.request_timeout,
                        # Socket close, up to three joins, then the bounded response write.
                        settlement=4 * config.close_timeout + config.request_timeout,
                    ),
                )
            reading = asyncio.create_task(read_frame(reader))
            while self._close_task is None:
                message = await reading
                if message == CLOSE:
                    return
                if message[:1] != REQUEST:
                    raise ValueError("Invalid inference request")
                # A live client sends nothing before its response, so a read that ends
                # first means it left: withdraw a queued request instead of running it.
                reading = asyncio.create_task(read_frame(reader))
                work = asyncio.create_task(self._respond(method, message[1:]))
                await asyncio.wait((work, reading), return_when=asyncio.FIRST_COMPLETED)
                if not work.done():
                    # A dispatched request still settles on its worker; nobody reads it.
                    return
                async with asyncio.timeout(config.request_timeout):
                    await write_frame(writer, work.result())
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError, TimeoutError):
            pass
        finally:
            tasks = tuple(task for task in (reading, work) if task is not None)
            for task in tasks:
                task.cancel()
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
                await close_writer(writer, config.close_timeout)
            finally:
                self._client_writers.discard(writer)

    async def do_inference(
        self, method: str, data: bytes, *, timeout: float | None = None
    ) -> bytes | None:
        if not self._serving:
            raise RuntimeError("Inference runtime is not ready")
        if method not in self._runner_classes:
            raise ValueError(f"Inference runner {method!r} is not registered")
        config = self._config
        if timeout is not None:
            # One explicit budget bounds the wait for a worker and the execution separately.
            timeout = positive_timeout(timeout, "request timeout")
        return await self._pools[method].run(
            data,
            queue_timeout=timeout or config.queue_timeout,
            timeout=timeout or config.request_timeout,
        )

    async def recover_failed_runners(self) -> bool:
        """Rebuild failed workers one at a time; never replay an attempted request.

        A caller owns the policy for failing the Host if safe reclamation or
        a bounded restart is unsuccessful. Only ready replacements are exposed,
        and healthy workers of the same method keep serving meanwhile. The
        restart budget is per method, shared by its workers.
        """
        config = self._config
        async with self._recovery_lock:
            if self._close_task is not None or not self._started:
                return False
            for index, (method, pool) in enumerate(self._pools.items(), start=1):
                for slot, previous in enumerate(pool.slots):
                    if previous is not None and previous.is_alive:
                        continue
                    now = time.monotonic()
                    history = self._restart_history[method]
                    while history and now - history[0] >= config.restart_window_seconds:
                        history.popleft()
                    if len(history) >= config.restart_limit:
                        logger.error(
                            "Inference runner restart limit reached method=%s attempts=%d "
                            "window_seconds=%.1f",
                            method,
                            len(history),
                            config.restart_window_seconds,
                        )
                        return False

                    logger.warning(
                        "Inference runner recovery starting method=%s worker=%d pid=%s "
                        "exitcode=%s attempt=%d/%d",
                        method,
                        slot,
                        previous.pid if previous is not None else None,
                        previous.exitcode if previous is not None else None,
                        len(history) + 1,
                        config.restart_limit,
                    )
                    try:
                        if previous is not None:
                            # Never start a duplicate while the old process may survive.
                            await self._close_runner(method, previous)
                            pool.slots[slot] = None
                        history.append(now)
                        pool.restarts += 1
                        await self._initialize_runner(method, (slot,), index)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Inference runner recovery failed method=%s", method)
                        return False
                    logger.info("Inference runner recovered method=%s worker=%d", method, slot)
            return self.is_alive

    async def _close(self) -> None:
        self._started = False
        if self._start_task is not None:
            if not self._start_task.done():
                self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        if self._directory_task is not None:
            results = await asyncio.gather(self._directory_task, return_exceptions=True)
            if isinstance(results[0], tuple):
                self._socket_dir = results[0][0]
        if self._listen_task is not None:
            await asyncio.gather(self._listen_task, return_exceptions=True)
        errors: list[Exception] = []
        if self._server is not None:
            self._server.close()
        tasks = tuple(self._client_tasks)
        for writer in tuple(self._client_writers):
            writer.close()
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors.extend(result for result in results if isinstance(result, Exception))
        runners = tuple(
            (method, slot, worker)
            for method, pool in reversed(self._pools.items())
            for slot, worker in enumerate(pool.slots)
            if worker is not None
        )
        results = await asyncio.gather(
            *(self._close_runner(method, worker) for method, _, worker in runners),
            return_exceptions=True,
        )
        for (method, slot, _), result in zip(runners, results, strict=True):
            if result is None:
                self._pools[method].slots[slot] = None
            elif isinstance(result, asyncio.CancelledError):
                errors.append(RuntimeError("Inference process cleanup cancelled unexpectedly"))
            elif isinstance(result, Exception):
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result
        if self._server is not None:
            try:
                await self._server.wait_closed()
            except Exception as error:
                errors.append(error)
            self._server = None
        if self._client_error is not None and self._client_error not in errors:
            errors.append(self._client_error)
        self._client_tasks.clear()
        self._client_writers.clear()
        if self._endpoint is not None and os.environ.get(INFERENCE_ENDPOINT_ENV) == self._endpoint:
            os.environ.pop(INFERENCE_ENDPOINT_ENV, None)
        if self._socket_dir is not None:
            try:
                await asyncio.to_thread(shutil.rmtree, self._socket_dir)
            except FileNotFoundError:
                pass
            except Exception as error:
                errors.append(error)
        self._socket_dir = self._endpoint = None
        if errors:
            raise ExceptionGroup("Inference runtime shutdown failed", errors)

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="inference_runtime_close")
            self._close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._close_task)
