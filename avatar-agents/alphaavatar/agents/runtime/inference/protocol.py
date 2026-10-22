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
import socket
import struct
from math import isfinite

INFERENCE_ENDPOINT_ENV = "ALPHAAVATAR_INFERENCE_ENDPOINT"
MAX_FRAME_BYTES = 64 * 1024 * 1024
HEADER = struct.Struct("!I")
_READY_BUDGETS = struct.Struct("!ddd")

REQUEST, CLOSE, CONNECT = b"\x01", b"\x02", b"\x03"
READY, INIT_ERROR, RESULT = b"\x10", b"\x11", b"\x12"
RESULT_NONE, RUN_ERROR, CLOSED, CLOSE_ERROR = b"\x13", b"\x14", b"\x15", b"\x16"


def positive_timeout(value: float, name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return float(value)


def service_ready(*, queue: float, execution: float, settlement: float) -> bytes:
    values = tuple(
        positive_timeout(value, "service budget") for value in (queue, execution, settlement)
    )
    positive_timeout(sum(values), "combined service budget")
    return READY + _READY_BUDGETS.pack(*values)


def service_budget(message: bytes) -> float:
    if message[:1] != READY or len(message) != 1 + _READY_BUDGETS.size:
        raise ValueError("Inference handshake is missing its service budgets")
    values = _READY_BUDGETS.unpack(message[1:])
    return positive_timeout(
        sum(positive_timeout(value, "service budget") for value in values),
        "combined service budget",
    )


def positive_limit(value: int, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_method(method: str) -> None:
    if not isinstance(method, str) or not method or method != method.strip():
        raise ValueError("Inference method must be a nonempty trimmed string")
    if len(method.encode("utf-8")) > 512:
        raise ValueError("Inference method exceeds 512 bytes")


def validate_data(data: bytes) -> None:
    if not isinstance(data, bytes):
        raise TypeError("Inference requests require immutable bytes")
    if len(data) >= MAX_FRAME_BYTES:
        raise ValueError("Inference request exceeds the frame limit")


def _size(size: int) -> int:
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ValueError("Invalid inference frame length")
    return size


def send_frame(sock: socket.socket, data: bytes) -> None:
    sock.sendall(HEADER.pack(_size(len(data))))
    sock.sendall(data)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = sock.recv(size - len(result))
        if not chunk:
            raise EOFError("Inference connection closed")
        result.extend(chunk)
    return bytes(result)


def recv_frame(sock: socket.socket) -> bytes:
    size = _size(HEADER.unpack(_recv_exact(sock, HEADER.size))[0])
    return _recv_exact(sock, size)


async def read_frame(reader: asyncio.StreamReader) -> bytes:
    size = _size(HEADER.unpack(await reader.readexactly(HEADER.size))[0])
    return await reader.readexactly(size)


async def write_frame(writer: asyncio.StreamWriter, data: bytes) -> None:
    writer.write(HEADER.pack(_size(len(data))))
    writer.write(data)
    await writer.drain()


async def close_writer(writer: asyncio.StreamWriter, timeout: float) -> None:
    writer.close()
    try:
        async with asyncio.timeout(timeout):
            await writer.wait_closed()
    except (ConnectionError, OSError):
        pass
    except BaseException:
        writer.transport.abort()
        raise
