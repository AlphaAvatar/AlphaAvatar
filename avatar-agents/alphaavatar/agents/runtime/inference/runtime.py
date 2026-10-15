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
import multiprocessing as mp
import os
import shutil
import tempfile
from multiprocessing.context import BaseContext

from alphaavatar.core.cleanup import wait_for_cleanup

from .process import RunnerProcess
from .protocol import (
    CLOSE,
    CONNECT,
    INFERENCE_ENDPOINT_ENV,
    READY,
    REQUEST,
    RESULT,
    RESULT_NONE,
    RUN_ERROR,
    close_writer,
    positive_limit,
    positive_timeout,
    read_frame,
    validate_method,
    write_frame,
)
from .runner import InferenceRunner


class InferenceRuntime:
    """Own one local endpoint and a bounded set of serial, independently spawned runners."""

    def __init__(
        self,
        runners: dict[str, type[InferenceRunner]],
        *,
        mp_ctx: BaseContext | None = None,
        initialize_timeout: float = 300,
        request_timeout: float = 30,
        close_timeout: float = 5,
        max_clients: int = 256,
        max_pending_per_runner: int = 64,
        handshake_timeout: float = 10,
    ) -> None:
        self._runner_classes = dict(runners)
        for method, runner in self._runner_classes.items():
            validate_method(method)
            if not isinstance(runner, type) or not issubclass(runner, InferenceRunner):
                raise TypeError("Inference plans require InferenceRunner classes")
            if runner.INFERENCE_METHOD != method:
                raise ValueError("Inference plan method does not match its runner")

        self._mp_ctx = mp_ctx or mp.get_context("spawn")
        if self._mp_ctx.get_start_method() == "fork":
            raise ValueError("Inference processes require spawn or forkserver, not fork")

        self._initialize_timeout = positive_timeout(initialize_timeout, "initialize_timeout")
        self._request_timeout = positive_timeout(request_timeout, "request_timeout")
        self._close_timeout = positive_timeout(close_timeout, "close_timeout")
        self._handshake_timeout = positive_timeout(handshake_timeout, "handshake_timeout")
        self._max_clients = positive_limit(max_clients, "max_clients")
        self._max_pending = positive_limit(max_pending_per_runner, "max_pending_per_runner")
        self._runners: dict[str, RunnerProcess] = {}
        self._server: asyncio.Server | None = None
        self._endpoint: str | None = None
        self._socket_dir: str | None = None
        self._client_tasks: set[asyncio.Task[None]] = set()
        self._client_writers: set[asyncio.StreamWriter] = set()
        self._start_task: asyncio.Task[None] | None = None
        self._directory_task: asyncio.Task[str] | None = None
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
    def is_alive(self) -> bool:
        return bool(
            self._started
            and self._close_task is None
            and self._server is not None
            and self._server.is_serving()
            and all(runner.is_alive for runner in self._runners.values())
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
            asyncio.to_thread(tempfile.mkdtemp, prefix="alphaavatar-inference-")
        )
        self._directory_task.add_done_callback(self._observe)
        self._socket_dir = await asyncio.shield(self._directory_task)
        self._endpoint = f"{self._socket_dir}/runtime.sock"
        self._listen_task = asyncio.create_task(self._listen())
        self._listen_task.add_done_callback(self._observe)
        await asyncio.shield(self._listen_task)

        # Export before the first forkserver starts so job processes inherit the final path.
        if os.environ.get(INFERENCE_ENDPOINT_ENV):
            raise RuntimeError("Another inference runtime acquired the process endpoint")

        os.environ[INFERENCE_ENDPOINT_ENV] = self._endpoint
        for method, runner_cls in self._runner_classes.items():
            runner = RunnerProcess(
                runner_cls,
                mp_ctx=self._mp_ctx,
                initialize_timeout=self._initialize_timeout,
                request_timeout=self._request_timeout,
                close_timeout=self._close_timeout,
                max_pending=self._max_pending,
            )
            self._runners[method] = runner  # Own partial initialization before the first await.
            await runner.start()

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
        if not self.is_alive or len(self._client_tasks) >= self._max_clients:
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

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            async with asyncio.timeout(self._handshake_timeout):
                message = await read_frame(reader)
                if message[:1] != CONNECT:
                    raise ValueError("Invalid inference handshake")
                method = message[1:].decode("utf-8")
                validate_method(method)
                runner = self._runners.get(method)
                if runner is None:
                    await write_frame(writer, RUN_ERROR + b"Inference method is not registered")
                    return
                await write_frame(writer, READY)
            while self._close_task is None:
                message = await read_frame(reader)
                if message == CLOSE:
                    return
                if message[:1] != REQUEST:
                    raise ValueError("Invalid inference request")
                try:
                    result = await runner.run(message[1:])
                    response = RESULT_NONE if result is None else RESULT + result
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    # Results are never retried. The caller learns failure, not a guessed outcome.
                    response = RUN_ERROR + str(error).encode("utf-8", errors="replace")[-16384:]
                async with asyncio.timeout(self._request_timeout):
                    await write_frame(writer, response)
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError, TimeoutError):
            pass
        finally:
            try:
                await close_writer(writer, self._close_timeout)
            finally:
                self._client_writers.discard(writer)

    async def do_inference(
        self, method: str, data: bytes, *, timeout: float | None = None
    ) -> bytes | None:
        if not self.is_alive:
            raise RuntimeError("Inference runtime is not ready")
        runner = self._runners.get(method)
        if runner is None:
            raise ValueError(f"Inference runner {method!r} is not registered")
        return await runner.run(data, timeout=timeout)

    async def _close(self) -> None:
        self._started = False
        if self._start_task is not None:
            if not self._start_task.done():
                self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        if self._directory_task is not None:
            results = await asyncio.gather(self._directory_task, return_exceptions=True)
            if isinstance(results[0], str):
                self._socket_dir = results[0]
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
        runners = tuple(reversed(tuple(self._runners.items())))
        results = await asyncio.gather(
            *(runner.close() for _, runner in runners),
            return_exceptions=True,
        )
        for (method, _), result in zip(runners, results, strict=True):
            if result is None:
                self._runners.pop(method, None)
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
