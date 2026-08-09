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
import socket
import struct
import tempfile
import traceback
from multiprocessing.context import BaseContext

from .runner import InferenceRunner

INFERENCE_ENDPOINT_ENV = "ALPHAAVATAR_INFERENCE_ENDPOINT"

_HEADER = struct.Struct("!I")

_REQUEST = b"\x01"
_CLOSE = b"\x02"
_CONNECT = b"\x03"

_READY = b"\x10"
_INIT_ERROR = b"\x11"
_RESULT = b"\x12"
_RESULT_NONE = b"\x13"
_RUN_ERROR = b"\x14"


def _send_frame(sock: socket.socket, data: bytes) -> None:
    sock.sendall(_HEADER.pack(len(data)) + data)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()

    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise EOFError("Inference process connection closed")
        chunks.extend(chunk)

    return bytes(chunks)


def _recv_frame(sock: socket.socket) -> bytes:
    size = _HEADER.unpack(_recv_exact(sock, _HEADER.size))[0]
    return _recv_exact(sock, size)


def _runner_process_main(
    runner_cls: type[InferenceRunner],
    sock: socket.socket,
) -> None:
    runner: InferenceRunner | None = None

    try:
        runner = runner_cls()
        runner.initialize()
        _send_frame(sock, _READY)

    except BaseException:
        _send_frame(
            sock,
            _INIT_ERROR + traceback.format_exc().encode(),
        )
        sock.close()
        return

    try:
        while True:
            message = _recv_frame(sock)
            operation = message[:1]

            if operation == _CLOSE:
                break

            if operation != _REQUEST:
                continue

            try:
                result = runner.run(message[1:])
                response = _RESULT_NONE if result is None else _RESULT + result
            except BaseException:
                response = _RUN_ERROR + traceback.format_exc().encode()

            _send_frame(sock, response)

    except (EOFError, ConnectionError, OSError):
        pass

    finally:
        try:
            runner.close()
        finally:
            sock.close()


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    size = _HEADER.unpack(await reader.readexactly(_HEADER.size))[0]
    return await reader.readexactly(size)


async def _write_frame(
    writer: asyncio.StreamWriter,
    data: bytes,
) -> None:
    writer.write(_HEADER.pack(len(data)) + data)
    await writer.drain()


class _RunnerProcess:
    def __init__(
        self,
        runner_cls: type[InferenceRunner],
        *,
        mp_ctx: BaseContext,
        initialize_timeout: float,
        request_timeout: float,
        close_timeout: float,
    ) -> None:
        self.method = runner_cls.INFERENCE_METHOD
        self._runner_cls = runner_cls
        self._mp_ctx = mp_ctx
        self._initialize_timeout = initialize_timeout
        self._request_timeout = request_timeout
        self._close_timeout = close_timeout

        self._process: mp.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    async def start(self) -> None:
        if self.is_alive:
            return

        parent_sock, child_sock = socket.socketpair()
        parent_sock.setblocking(False)

        process = self._mp_ctx.Process(
            target=_runner_process_main,
            args=(self._runner_cls, child_sock),
            name=f"inference:{self.method}",
        )

        try:
            process.start()
            child_sock.close()

            reader, writer = await asyncio.open_connection(
                sock=parent_sock,
            )
            response = await asyncio.wait_for(
                _read_frame(reader),
                timeout=self._initialize_timeout,
            )

            if response[:1] == _INIT_ERROR:
                raise RuntimeError(response[1:].decode(errors="replace"))

            if response != _READY:
                raise RuntimeError(f"Invalid initialization response from `{self.method}`")

            self._process = process
            self._reader = reader
            self._writer = writer

        except BaseException:
            parent_sock.close()
            child_sock.close()

            if process.is_alive():
                process.terminate()
                process.join(timeout=1)

            raise

    async def run(
        self,
        data: bytes,
        *,
        timeout: float | None = None,
    ) -> bytes | None:
        async with self._lock:
            if not self.is_alive or self._reader is None or self._writer is None:
                raise RuntimeError(f"Inference runner `{self.method}` is not running")

            self._writer.write(_HEADER.pack(len(data) + 1) + _REQUEST + data)
            await self._writer.drain()

            try:
                response = await asyncio.wait_for(
                    _read_frame(self._reader),
                    timeout=timeout or self._request_timeout,
                )
            except TimeoutError:
                await self._terminate()
                raise TimeoutError(f"Inference runner `{self.method}` timed out") from None

            operation = response[:1]

            if operation == _RESULT:
                return response[1:]

            if operation == _RESULT_NONE:
                return None

            if operation == _RUN_ERROR:
                raise RuntimeError(response[1:].decode(errors="replace"))

            raise RuntimeError(f"Invalid response from inference runner `{self.method}`")

    async def close(self) -> None:
        async with self._lock:
            if self._writer is not None:
                try:
                    self._writer.write(_HEADER.pack(1) + _CLOSE)
                    await self._writer.drain()
                except (ConnectionError, OSError):
                    pass

            await self._terminate()

    async def _terminate(self) -> None:
        writer = self._writer
        process = self._process

        self._reader = None
        self._writer = None
        self._process = None

        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

        if process is None:
            return

        deadline = asyncio.get_running_loop().time() + self._close_timeout

        while process.is_alive():
            if asyncio.get_running_loop().time() >= deadline:
                process.terminate()
                break

            await asyncio.sleep(0.02)

        process.join(timeout=1)

        if process.is_alive():
            process.kill()
            process.join(timeout=1)

        process.close()


class InferenceRuntime:
    def __init__(
        self,
        runners: dict[str, type[InferenceRunner]] | None = None,
        *,
        mp_ctx: BaseContext | None = None,
        initialize_timeout: float = 300,
        request_timeout: float = 30,
        close_timeout: float = 5,
    ) -> None:
        self._runner_classes = dict(
            InferenceRunner.registered_runners if runners is None else runners
        )
        self._mp_ctx = mp_ctx or mp.get_context()
        self._initialize_timeout = initialize_timeout
        self._request_timeout = request_timeout
        self._close_timeout = close_timeout

        self._runners: dict[str, _RunnerProcess] = {}
        self._server: asyncio.Server | None = None
        self._endpoint: str | None = None
        self._socket_dir: str | None = None
        self._client_tasks: set[asyncio.Task] = set()
        self._client_writers: set[asyncio.StreamWriter] = set()
        self._started = False

    @property
    def methods(self) -> tuple[str, ...]:
        return tuple(self._runner_classes)

    @property
    def endpoint(self) -> str:
        if self._endpoint is None:
            raise RuntimeError("Inference runtime is not started")
        return self._endpoint

    @property
    def is_alive(self) -> bool:
        return (
            self._started
            and self._server is not None
            and self._server.is_serving()
            and all(runner.is_alive for runner in self._runners.values())
        )

    async def start(self) -> None:
        if self._started:
            return

        try:
            self._socket_dir = tempfile.mkdtemp(prefix="alphaavatar-inference-")
            self._endpoint = f"{self._socket_dir}/runtime.sock"
            self._server = await asyncio.start_unix_server(
                self._accept_client,
                path=self._endpoint,
            )

            os.environ[INFERENCE_ENDPOINT_ENV] = self._endpoint

            for method, runner_cls in self._runner_classes.items():
                runner = _RunnerProcess(
                    runner_cls,
                    mp_ctx=self._mp_ctx,
                    initialize_timeout=self._initialize_timeout,
                    request_timeout=self._request_timeout,
                    close_timeout=self._close_timeout,
                )
                await runner.start()
                self._runners[method] = runner

        except BaseException:
            await self.close()
            raise

        self._started = True

    def _accept_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.create_task(
            self._handle_client(reader, writer),
            name="inference_client",
        )
        self._client_tasks.add(task)
        task.add_done_callback(self._client_tasks.discard)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._client_writers.add(writer)

        try:
            message = await _read_frame(reader)

            if message[:1] != _CONNECT:
                await _write_frame(
                    writer,
                    _RUN_ERROR + b"Invalid inference handshake",
                )
                return

            method = message[1:].decode()
            runner = self._runners.get(method)

            if runner is None:
                await _write_frame(
                    writer,
                    _RUN_ERROR + f"Inference runner `{method}` is not registered".encode(),
                )
                return

            await _write_frame(writer, _READY)

            while True:
                message = await _read_frame(reader)
                operation = message[:1]

                if operation == _CLOSE:
                    return

                if operation != _REQUEST:
                    await _write_frame(
                        writer,
                        _RUN_ERROR + b"Invalid inference request",
                    )
                    continue

                try:
                    result = await runner.run(message[1:])
                    response = _RESULT_NONE if result is None else _RESULT + result
                except BaseException:
                    response = _RUN_ERROR + traceback.format_exc().encode()

                await _write_frame(writer, response)

        except (
            asyncio.IncompleteReadError,
            ConnectionError,
            OSError,
        ):
            pass

        finally:
            self._client_writers.discard(writer)
            writer.close()

            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def do_inference(
        self,
        method: str,
        data: bytes,
        *,
        timeout: float | None = None,
    ) -> bytes | None:
        runner = self._runners.get(method)

        if runner is None:
            raise ValueError(f"Inference runner `{method}` is not registered")

        return await runner.run(data, timeout=timeout)

    async def close(self) -> None:
        server = self._server
        writers = list(self._client_writers)
        tasks = list(self._client_tasks)
        socket_dir = self._socket_dir
        endpoint = self._endpoint

        self._server = None
        self._endpoint = None
        self._socket_dir = None
        self._client_writers.clear()
        self._client_tasks.clear()
        self._started = False

        if server is not None:
            server.close()
            await server.wait_closed()

        for writer in writers:
            writer.close()

        await asyncio.gather(
            *(writer.wait_closed() for writer in writers),
            return_exceptions=True,
        )

        for task in tasks:
            task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        runners = list(reversed(self._runners.values()))
        self._runners.clear()

        await asyncio.gather(
            *(runner.close() for runner in runners),
            return_exceptions=True,
        )

        if endpoint is not None and os.environ.get(INFERENCE_ENDPOINT_ENV) == endpoint:
            os.environ.pop(INFERENCE_ENDPOINT_ENV, None)

        if socket_dir is not None:
            shutil.rmtree(socket_dir, ignore_errors=True)
