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
from contextlib import suppress

from .runtime import (
    _CLOSE,
    _CONNECT,
    _READY,
    _REQUEST,
    _RESULT,
    _RESULT_NONE,
    _RUN_ERROR,
    INFERENCE_ENDPOINT_ENV,
    _read_frame,
    _write_frame,
)


class _InferenceConnection:
    def __init__(
        self,
        endpoint: str,
        method: str,
    ) -> None:
        self._endpoint = endpoint
        self._method = method
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def _connect(self) -> None:
        if self._reader is not None and self._writer is not None:
            return

        reader, writer = await asyncio.open_unix_connection(self._endpoint)

        try:
            await _write_frame(
                writer,
                _CONNECT + self._method.encode(),
            )
            response = await _read_frame(reader)

            if response == _READY:
                self._reader = reader
                self._writer = writer
                return

            if response[:1] == _RUN_ERROR:
                raise ValueError(response[1:].decode(errors="replace"))

            raise RuntimeError(f"Invalid handshake response for `{self._method}`")

        except BaseException:
            writer.close()

            with suppress(
                asyncio.CancelledError,
                ConnectionError,
                OSError,
            ):
                await writer.wait_closed()

            raise

    def _drop(self) -> asyncio.StreamWriter | None:
        writer = self._writer

        self._reader = None
        self._writer = None

        if writer is not None:
            writer.close()

        return writer

    async def run(self, data: bytes) -> bytes | None:
        async with self._lock:
            await self._connect()

            reader = self._reader
            writer = self._writer

            if reader is None or writer is None:
                raise RuntimeError(f"Inference connection `{self._method}` is unavailable")

            try:
                await _write_frame(
                    writer,
                    _REQUEST + data,
                )
                response = await _read_frame(reader)

            except BaseException:
                self._drop()
                raise

            operation = response[:1]

            if operation == _RESULT:
                return response[1:]

            if operation == _RESULT_NONE:
                return None

            if operation == _RUN_ERROR:
                raise RuntimeError(response[1:].decode(errors="replace"))

            self._drop()
            raise RuntimeError(f"Invalid response from inference runner `{self._method}`")

    async def close(self) -> None:
        async with self._lock:
            writer = self._writer

            if writer is not None:
                with suppress(
                    asyncio.CancelledError,
                    ConnectionError,
                    OSError,
                ):
                    await _write_frame(writer, _CLOSE)

            writer = self._drop()

            if writer is not None:
                with suppress(
                    asyncio.CancelledError,
                    ConnectionError,
                    OSError,
                ):
                    await writer.wait_closed()


class InferenceExecutor:
    def __init__(self, endpoint: str) -> None:
        if not endpoint:
            raise ValueError("Inference endpoint cannot be empty")

        self._endpoint = endpoint
        self._connections: dict[str, _InferenceConnection] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @classmethod
    def from_env(cls) -> InferenceExecutor:
        endpoint = os.getenv(INFERENCE_ENDPOINT_ENV)

        if not endpoint:
            raise RuntimeError(f"{INFERENCE_ENDPOINT_ENV} is not configured")

        return cls(endpoint)

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Inference executor is closed")

            connection = self._connections.get(method)

            if connection is None:
                connection = _InferenceConnection(
                    self._endpoint,
                    method,
                )
                self._connections[method] = connection

        return await connection.run(data)

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return

            self._closed = True
            connections = list(self._connections.values())
            self._connections.clear()

        await asyncio.gather(
            *(connection.close() for connection in connections),
            return_exceptions=True,
        )
