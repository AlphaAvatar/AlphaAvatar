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

from .schemas import MAX_MESSAGE_BYTES, ProcessMessage


async def receive(reader: asyncio.StreamReader) -> ProcessMessage:
    line = await reader.readline()
    if not line:
        raise EOFError("Execution control channel closed")
    if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
        raise ValueError("Invalid execution control frame")
    return ProcessMessage.model_validate_json(line)


async def send(writer: asyncio.StreamWriter, message: ProcessMessage, timeout: float) -> None:
    data = message.model_dump_json().encode("utf-8") + b"\n"
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("Execution control frame is too large")
    async with asyncio.timeout(timeout):
        writer.write(data)
        await writer.drain()
