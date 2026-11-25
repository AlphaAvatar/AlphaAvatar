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
import os
from typing import TYPE_CHECKING

from alphaavatar.core.cleanup import wait_for_cleanup

from .protocol import (
    CONNECT,
    INFERENCE_SOCKET_ENV,
    REQUEST,
    RESULT,
    RESULT_NONE,
    RUN_ERROR,
    close_writer,
    positive_limit,
    positive_timeout,
    read_frame,
    service_budget,
    validate_data,
    validate_method,
    write_frame,
)

if TYPE_CHECKING:
    from alphaavatar.agents.configs.runtime_config import InferenceConfig


class _InferenceConnection:
    def __init__(
        self,
        socket_path: str,
        method: str,
        *,
        request_timeout: float,
        close_timeout: float,
        max_pending: int,
    ) -> None:
        self._socket_path, self._method = socket_path, method
        self._request_timeout, self._close_timeout = request_timeout, close_timeout
        self._max_pending = max_pending
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._service_budget = 0.0
        self._requests: set[asyncio.Task[bytes | None]] = set()
        self._retiring: set[asyncio.Task[None]] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._cleanup_error: Exception | None = None

    @staticmethod
    def _observe(task: asyncio.Future) -> None:
        if not task.cancelled():
            task.exception()

    def _drop(self) -> None:
        writer = self._writer
        self._reader = self._writer = None
        self._service_budget = 0.0
        if writer is None:
            return
        writer.close()
        task = asyncio.create_task(close_writer(writer, self._close_timeout))
        self._retiring.add(task)
        task.add_done_callback(self._retiring.discard)
        task.add_done_callback(self._observe_retirement)

    def _observe_retirement(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self._cleanup_error = self._cleanup_error or RuntimeError(
                "Inference connection retirement cancelled unexpectedly"
            )
        elif (error := task.exception()) is not None:
            self._cleanup_error = self._cleanup_error or error

    async def _connect(self) -> None:
        if self._writer is not None:
            return

        self._reader, self._writer = await asyncio.open_unix_connection(self._socket_path)
        await write_frame(self._writer, CONNECT + self._method.encode("utf-8"))
        response = await read_frame(self._reader)
        self._service_budget = service_budget(response)

    async def _run(self, data: bytes) -> bytes | None:
        # Local connection serialization must not consume this call's network
        # timeout. Remote service queueing retains its own bounded deadlines.
        async with asyncio.timeout(self._request_timeout):
            await self._lock.acquire()
        try:
            if self._close_task is not None:
                raise RuntimeError("Inference connection is closed")
            try:
                async with asyncio.timeout(self._request_timeout):
                    await self._connect()
                    await write_frame(self._writer, REQUEST + data)
                # Transport timeout cannot silently undercut the service's valid queue/execution.
                async with asyncio.timeout(self._service_budget + self._close_timeout):
                    response = await read_frame(self._reader)
            except BaseException:
                self._drop()
                raise
            if response[:1] == RESULT:
                return response[1:]
            if response == RESULT_NONE:
                return None
            if response[:1] == RUN_ERROR:
                raise RuntimeError(response[1:].decode(errors="replace"))
            self._drop()
            raise RuntimeError(f"Invalid inference response for {self._method!r}")
        finally:
            self._lock.release()

    async def run(self, data: bytes) -> bytes | None:
        if self._close_task is not None:
            raise RuntimeError("Inference connection is closed")
        if len(self._requests) + len(self._retiring) >= self._max_pending:
            raise RuntimeError(f"Inference connection {self._method!r} is at capacity")
        task = asyncio.create_task(self._run(data), name=f"inference_request:{self._method}")
        self._requests.add(task)
        task.add_done_callback(self._requests.discard)
        task.add_done_callback(self._observe)
        # Client cancellation drops its channel. The server owns any dispatched exchange.
        return await task

    async def _close(self) -> None:
        self._drop()
        tasks = tuple(self._requests)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        results = await asyncio.gather(*tuple(self._retiring), return_exceptions=True)
        errors = [result for result in results if isinstance(result, Exception)]
        if self._cleanup_error is not None and self._cleanup_error not in errors:
            errors.append(self._cleanup_error)
        if errors:
            raise ExceptionGroup("Inference connection cleanup failed", errors)

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="inference_connection_close")
            self._close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._close_task)


class _InferenceChannels:
    """Up to one serial connection per service worker; a call takes the oldest idle one.

    A connection carries one exchange at a time, so each response belongs to the call
    holding it. Waiting calls queue here, bounded by count and by the local timeout;
    close returns only after every running and waiting call has left.
    """

    def __init__(
        self,
        socket_path: str,
        method: str,
        *,
        channels: int,
        request_timeout: float,
        close_timeout: float,
        max_pending: int,
    ) -> None:
        self._method, self._request_timeout, self._max_pending = (
            method,
            request_timeout,
            max_pending,
        )
        self._connections = tuple(
            _InferenceConnection(
                socket_path,
                method,
                request_timeout=request_timeout,
                close_timeout=close_timeout,
                max_pending=max_pending,
            )
            for _ in range(channels)
        )
        self._idle: asyncio.Queue[_InferenceConnection] = asyncio.Queue()
        for connection in self._connections:
            self._idle.put_nowait(connection)
        self._pending = 0
        self._settled = asyncio.Event()
        self._settled.set()

    async def run(self, data: bytes) -> bytes | None:
        if self._pending >= self._max_pending:
            raise RuntimeError(f"Inference connection {self._method!r} is at capacity")
        self._pending += 1
        self._settled.clear()
        try:
            # Waiting for a channel is local and does not consume the network timeout.
            async with asyncio.timeout(self._request_timeout):
                connection = await self._idle.get()
            try:
                return await connection.run(data)
            finally:
                self._idle.put_nowait(connection)
        finally:
            self._pending -= 1
            if not self._pending:
                self._settled.set()

    async def close(self) -> None:
        results = await asyncio.gather(
            *(connection.close() for connection in self._connections), return_exceptions=True
        )
        # Each closed channel returns to the queue and refuses its local waiters in turn.
        await self._settled.wait()
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise ExceptionGroup("Inference connection cleanup failed", errors)


class InferenceExecutor:
    """A bounded local client. It owns sockets, never the server or inference processes.

    Limits come from the same accepted ``runtime.inference`` the Host served: one channel
    per worker of each method, ``max_pending`` calls per method, and ``client_timeout``
    for the local wait, connect and send. The response wait is the service's own budget.
    """

    def __init__(
        self, socket_path: str, config: InferenceConfig | None = None, *, max_connections: int = 128
    ) -> None:
        if not isinstance(socket_path, str) or not socket_path:
            raise ValueError("Inference socket path cannot be empty")
        if config is None:
            from alphaavatar.agents.configs.runtime_config import InferenceConfig

            config = InferenceConfig()

        self._socket_path, self._config = socket_path, config
        self._request_timeout = positive_timeout(config.client_timeout, "client_timeout")
        self._close_timeout = positive_timeout(config.close_timeout, "close_timeout")
        self._max_connections = positive_limit(max_connections, "max_connections")
        self._max_pending = positive_limit(config.max_pending, "max_pending")
        self._connections: dict[str, _InferenceChannels] = {}
        self._close_task: asyncio.Task[None] | None = None

    @classmethod
    def from_env(cls, config: InferenceConfig) -> InferenceExecutor:
        socket_path = os.getenv(INFERENCE_SOCKET_ENV)
        if not socket_path:
            raise RuntimeError(f"{INFERENCE_SOCKET_ENV} is not configured")
        return cls(socket_path, config)

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        validate_method(method)
        validate_data(data)
        if self._close_task is not None:
            raise RuntimeError("Inference executor is closed")
        channels = self._connections.get(method)
        if channels is None:
            if len(self._connections) >= self._max_connections:
                raise RuntimeError("Inference executor connection capacity exhausted")
            channels = _InferenceChannels(
                self._socket_path,
                method,
                channels=self._config.workers(method),
                request_timeout=self._request_timeout,
                close_timeout=self._close_timeout,
                max_pending=self._max_pending,
            )
            self._connections[method] = channels
        return await channels.run(data)

    async def _close(self) -> None:
        results = await asyncio.gather(
            *(connection.close() for connection in self._connections.values()),
            return_exceptions=True,
        )
        self._connections.clear()
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise ExceptionGroup("Inference executor cleanup failed", errors)

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="inference_executor_close")
            self._close_task.add_done_callback(_InferenceConnection._observe)
        await wait_for_cleanup(self._close_task)
