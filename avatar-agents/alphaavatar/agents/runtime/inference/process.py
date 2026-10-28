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
import importlib
import logging
import multiprocessing as mp
import socket
import sys
import time
from contextlib import nullcontext
from dataclasses import dataclass
from multiprocessing.context import BaseContext

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.log import configure_from_env, format_error
from alphaavatar.core.log.capture import capture_initialization_output

from .protocol import (
    CLOSE,
    CLOSE_ERROR,
    CLOSED,
    INIT_ERROR,
    READY,
    REQUEST,
    RESULT,
    RESULT_NONE,
    RUN_ERROR,
    close_writer,
    positive_timeout,
    read_frame,
    recv_frame,
    send_frame,
    validate_data,
    write_frame,
)
from .runner import InferenceRunner, RunnerLaunch
from .signals import configure_runner_signals, start_runner_process

logger = logging.getLogger(__name__)


def _error() -> bytes:
    error = sys.exception()
    diagnostic = format_error(error, details=True) if error else "runner_error"
    logger.error("Inference runner failed\n%s", diagnostic)
    return diagnostic.encode("utf-8")[:16384]


def _runner_main(
    runner_spec: tuple[str, str], sock: socket.socket, launch: RunnerLaunch | None = None
) -> None:
    configure_runner_signals()
    client = None
    try:
        client = configure_from_env()
        _serve_runner(runner_spec, sock, capture=client is not None, launch=launch)
    finally:
        sock.close()
        if client is not None:
            client.close()


def _serve_runner(
    runner_spec: tuple[str, str],
    sock: socket.socket,
    *,
    capture: bool,
    launch: RunnerLaunch | None = None,
) -> None:
    runner = None
    try:
        # Resolve model/plugin imports only after installing the signal and logging policy.
        with capture_initialization_output() if capture else nullcontext():
            runner_cls = importlib.import_module(runner_spec[0])
            for part in runner_spec[1].split("."):
                runner_cls = getattr(runner_cls, part)
            if not isinstance(runner_cls, type) or not issubclass(runner_cls, InferenceRunner):
                raise TypeError("Inference target must be an InferenceRunner class")
            runner = runner_cls()
            if launch is not None:
                runner.configure(launch)
            runner.initialize()
            configure_runner_signals()  # Model initialization does not own terminal shutdown.
    except BaseException:
        error = _error()
        if runner is not None:
            try:
                runner.close()
            except BaseException:
                error += b"\nInitialization cleanup failed:\n" + _error()
        try:
            send_frame(sock, INIT_ERROR + error)
        except (ConnectionError, OSError):
            pass
        finally:
            sock.close()
        return

    try:
        send_frame(sock, READY)
        while True:
            message = recv_frame(sock)
            if message == CLOSE:
                break
            if message[:1] != REQUEST:
                raise ValueError("Invalid runner operation")
            try:
                result = runner.run(message[1:])
                if result is not None:
                    validate_data(result)
                response = RESULT_NONE if result is None else RESULT + result
            except BaseException:
                response = RUN_ERROR + _error()
            send_frame(sock, response)
    except (EOFError, ConnectionError, OSError, ValueError):
        pass
    finally:
        response = CLOSED
        try:
            runner.close()
        except BaseException:
            response = CLOSE_ERROR + _error()
        try:
            send_frame(sock, response)
        except (ConnectionError, OSError):
            pass
        finally:
            sock.close()


@dataclass(slots=True)
class _Request:
    dispatched: bool = False


class RunnerProcess:
    """One serial runner, with owned exchanges and no response reuse after stream failure."""

    def __init__(
        self,
        runner_cls: type[InferenceRunner],
        *,
        mp_ctx: BaseContext,
        initialize_timeout: float,
        request_timeout: float,
        close_timeout: float,
        max_pending: int,
        launch: RunnerLaunch | None = None,
    ) -> None:
        self._launch = launch
        self.method = runner_cls.INFERENCE_METHOD
        self._runner_cls, self._mp_ctx = runner_cls, mp_ctx
        self._initialize_timeout, self._request_timeout = initialize_timeout, request_timeout
        self._close_timeout, self._max_pending = close_timeout, max_pending
        self._process: mp.Process | None = None
        self._sockets: tuple[socket.socket, socket.socket] | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._launch_task: asyncio.Task[None] | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._retire_task: asyncio.Task[None] | None = None
        self._requests: dict[asyncio.Task[bytes | None], _Request] = {}
        self._lock = asyncio.Lock()
        self._ready = self._broken = False
        self._stats_since = time.monotonic()
        self._stats_count = 0
        self._stats_queue = self._stats_execute = 0.0
        self._stats_max_queue = self._stats_max_execute = 0.0

    @property
    def is_alive(self) -> bool:
        return bool(
            self._ready
            and not self._broken
            and self._close_task is None
            and self._process is not None
            and self._process.is_alive()
        )

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def exitcode(self) -> int | None:
        return self._process.exitcode if self._process is not None else None

    @staticmethod
    def _observe(task: asyncio.Future) -> None:
        if not task.cancelled():
            task.exception()

    async def _connect(self, sock: socket.socket) -> None:
        self._reader, self._writer = await asyncio.open_connection(sock=sock)

    async def _start(self) -> None:
        parent, child = self._sockets = socket.socketpair()
        parent.setblocking(False)
        self._process = self._mp_ctx.Process(
            target=_runner_main,
            args=(
                (self._runner_cls.__module__, self._runner_cls.__qualname__),
                child,
                self._launch,
            ),
            name=f"inference:{self.method}",
        )

        # Spawn/forkserver launch and joins can block. Own them before moving off-loop.
        self._launch_task = asyncio.create_task(
            asyncio.to_thread(start_runner_process, self._process)
        )
        self._launch_task.add_done_callback(self._observe)
        async with asyncio.timeout(self._initialize_timeout):
            await asyncio.shield(self._launch_task)
            child.close()
            self._connect_task = asyncio.create_task(self._connect(parent))
            self._connect_task.add_done_callback(self._observe)
            await asyncio.shield(self._connect_task)
            response = await read_frame(self._reader)
            if response[:1] == INIT_ERROR:
                raise RuntimeError(response[1:].decode(errors="replace"))
            if response != READY:
                raise RuntimeError(f"Invalid initialization response from {self.method!r}")
        if self._close_task is not None:
            raise RuntimeError("Inference process closed during initialization")
        self._ready = True

    async def start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Inference process is closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name=f"init:{self.method}")
            self._start_task.add_done_callback(self._observe)
        try:
            await asyncio.shield(self._start_task)
            if not self.is_alive:
                raise RuntimeError(f"Inference process {self.method!r} is unavailable")
        except BaseException as original:
            try:
                await self.close()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    def _log_summary(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not self._stats_count or (not force and now - self._stats_since < 10.0):
            return

        logger.debug(
            "INFERENCE SUMMARY method=%s pid=%s calls=%d window_seconds=%.3f "
            "queue_avg_ms=%.3f queue_max_ms=%.3f execution_avg_ms=%.3f execution_max_ms=%.3f",
            self.method,
            self.pid,
            self._stats_count,
            now - self._stats_since,
            1000 * self._stats_queue / self._stats_count,
            1000 * self._stats_max_queue,
            1000 * self._stats_execute / self._stats_count,
            1000 * self._stats_max_execute,
        )
        self._stats_since, self._stats_count = now, 0
        self._stats_queue = self._stats_execute = 0.0
        self._stats_max_queue = self._stats_max_execute = 0.0

    async def _exchange(self, request: _Request, data: bytes, timeout: float) -> bytes | None:
        # Queue admission and a dispatched exchange have separate deadlines. Waiting
        # behind another request must not consume this request's execution budget.
        clock = time.monotonic
        queued_at = clock()
        acquired = False
        success = False
        stage = "queue"
        execute_at: float | None = None
        try:
            async with asyncio.timeout(timeout):
                await self._lock.acquire()
            acquired = True
            execute_at = clock()
            stage = "execution"
            async with asyncio.timeout(timeout):
                if not self.is_alive:
                    raise RuntimeError(f"Inference process {self.method!r} is unavailable")
                request.dispatched = True
                await write_frame(self._writer, REQUEST + data)
                response = await read_frame(self._reader)
                if response[:1] == RESULT:
                    success = True
                    return response[1:]
                if response == RESULT_NONE:
                    success = True
                    return None
                if response[:1] == RUN_ERROR:
                    # A fully consumed error response does not desynchronize the channel.
                    request.dispatched = False
                    raise RuntimeError(response[1:].decode(errors="replace"))
                raise RuntimeError(f"Invalid response from {self.method!r}")
        except BaseException as error:
            logger.log(
                logging.DEBUG if isinstance(error, asyncio.CancelledError) else logging.WARNING,
                "Inference exchange failed method=%s pid=%s exitcode=%s stage=%s "
                "queued_seconds=%.3f execution_seconds=%.3f dispatched=%s error_type=%s",
                self.method,
                self.pid,
                self.exitcode,
                stage,
                (execute_at or clock()) - queued_at,
                clock() - execute_at if execute_at is not None else 0.0,
                request.dispatched,
                type(error).__name__,
            )
            if request.dispatched:
                # A dispatched timeout leaves the runner's response ownership
                # unknowable. Retire that process; never reuse or replay its result.
                self._broken = True
                await wait_for_cleanup(self._retire(force=True))
            raise
        finally:
            if success and execute_at is not None:
                queued, executed = execute_at - queued_at, clock() - execute_at
                self._stats_count += 1
                self._stats_queue += queued
                self._stats_execute += executed
                self._stats_max_queue = max(self._stats_max_queue, queued)
                self._stats_max_execute = max(self._stats_max_execute, executed)
                self._log_summary()
            if acquired:
                self._lock.release()
            elif not request.dispatched:
                logger.debug(
                    "Inference queued request not dispatched method=%s wait_seconds=%.3f",
                    self.method,
                    clock() - queued_at,
                )

    async def run(self, data: bytes, *, timeout: float | None = None) -> bytes | None:
        validate_data(data)
        timeout = positive_timeout(
            self._request_timeout if timeout is None else timeout, "request timeout"
        )
        if not self.is_alive:
            raise RuntimeError(f"Inference process {self.method!r} is unavailable")
        if len(self._requests) >= self._max_pending:
            raise RuntimeError(f"Inference process {self.method!r} is at capacity")
        request = _Request()
        task = asyncio.create_task(
            self._exchange(request, data, timeout), name=f"infer:{self.method}"
        )
        self._requests[task] = request
        task.add_done_callback(lambda done: self._requests.pop(done, None))
        task.add_done_callback(self._observe)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Queued work can be withdrawn. Dispatched work must consume its own response.
            if not request.dispatched:
                task.cancel()
            raise

    async def _reap(self, *, force: bool) -> None:
        errors: list[Exception] = []
        if self._writer is not None:
            try:
                await close_writer(self._writer, self._close_timeout)
            except Exception as error:
                errors.append(error)
        self._reader = self._writer = None
        if self._sockets is not None:
            for sock in self._sockets:
                sock.close()
            self._sockets = None

        process = self._process
        if process is not None:
            old_pid, old_exitcode = process.pid, process.exitcode
            if process.pid is not None:
                if force and process.is_alive():
                    process.terminate()
                await asyncio.to_thread(process.join, self._close_timeout)
                if process.is_alive():
                    process.terminate()
                    await asyncio.to_thread(process.join, self._close_timeout)
                if process.is_alive():
                    process.kill()
                    await asyncio.to_thread(process.join, self._close_timeout)
                if process.is_alive():
                    errors.append(RuntimeError(f"Could not reap inference process {self.method!r}"))
                else:
                    old_exitcode = process.exitcode
                    process.close()
                    self._process = None
            else:
                process.close()
                self._process = None
            logger.info(
                "Inference process settled method=%s pid=%s exitcode=%s forced=%s reaped=%s",
                self.method,
                old_pid,
                old_exitcode,
                force,
                self._process is None,
            )
        if errors:
            raise ExceptionGroup("Inference process reclamation failed", errors)

    def _retire(self, *, force: bool) -> asyncio.Task[None]:
        if self._retire_task is None:
            self._retire_task = asyncio.create_task(
                self._reap(force=force), name=f"reap:{self.method}"
            )
            self._retire_task.add_done_callback(self._observe)
        return self._retire_task

    async def _close(self) -> None:
        errors: list[Exception] = []
        if self._start_task is not None:
            if not self._start_task.done():
                self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)

        # A cancelled await must not lose a process or transport acquired off-loop.
        for task in (self._launch_task, self._connect_task):
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)

        # If the child exited before its reader noticed EOF, close the socket
        # first and let the in-flight request observe failure. Do not cancel the
        # server's IPC handler as if it were an ordinary caller interruption.
        if self._process is not None and not self._process.is_alive():
            self._broken = True
        requests = tuple(self._requests)
        if self._broken:
            try:
                await wait_for_cleanup(self._retire(force=True))
            except Exception as error:
                errors.append(error)
                for task in requests:
                    task.cancel()
            await asyncio.gather(*requests, return_exceptions=True)
        else:
            for task in requests:
                task.cancel()
            await asyncio.gather(*requests, return_exceptions=True)

        self._log_summary(force=True)
        if self._ready and not self._broken and self._writer is not None:
            try:
                async with asyncio.timeout(self._close_timeout):
                    await write_frame(self._writer, CLOSE)
                    response = await read_frame(self._reader)
                    if response[:1] == CLOSE_ERROR:
                        raise RuntimeError(response[1:].decode(errors="replace"))
                    if response != CLOSED:
                        raise RuntimeError("Inference process did not acknowledge shutdown")
            except Exception as error:
                self._broken = True
                errors.append(error)
        self._ready = False
        try:
            await self._retire(force=self._broken)
        except Exception as error:
            errors.append(error)
        if errors:
            raise ExceptionGroup(f"Inference process {self.method!r} cleanup failed", errors)

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name=f"close:{self.method}")
            self._close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._close_task)
