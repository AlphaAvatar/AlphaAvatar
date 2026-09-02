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

import json
import struct
from enum import StrEnum
from typing import Any


class InvocationRunnerOperation(StrEnum):
    WARMUP = "warmup"
    PUSH = "push"
    FINISH = "finish"
    CLOSE = "close"


def encode_packet(
    header: dict[str, Any],
    payload: bytes = b"",
) -> bytes:
    encoded = json.dumps(
        header,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    return struct.pack("!I", len(encoded)) + encoded + payload


def decode_packet(
    data: bytes,
) -> tuple[dict[str, Any], bytes]:
    if len(data) < 4:
        raise ValueError("Invocation packet is too short")

    header_size = struct.unpack("!I", data[:4])[0]
    if len(data) < 4 + header_size:
        raise ValueError("Invocation packet header is incomplete")

    header = json.loads(data[4 : 4 + header_size].decode("utf-8"))
    return header, data[4 + header_size :]


def encode_response(
    *,
    labels: tuple[str, ...] = (),
) -> bytes:
    return encode_packet({"labels": list(labels)})


def decode_response(data: bytes) -> tuple[str, ...]:
    header, payload = decode_packet(data)

    if payload:
        raise ValueError("Invocation response has unexpected payload")

    return tuple(str(label) for label in header.get("labels", ()))
