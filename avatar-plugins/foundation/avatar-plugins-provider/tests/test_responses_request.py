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
"""The Responses request as it goes out: its pictures and the body the transport sends."""

from __future__ import annotations

import asyncio
import json

import httpx

from alphaavatar.plugins.provider.openai.llms.client import _record_sent, sending
from alphaavatar.plugins.provider.openai.llms.responses import _pictures


def test_the_pictures_a_request_carries_are_counted_from_its_encoded_input() -> None:
    picture = {"type": "input_image", "image_url": "data:image/jpeg;base64,AAAA"}
    payload = {
        "model": "m",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "a"}, picture, picture]},
            {"role": "assistant", "content": [{"type": "output_text", "text": "b"}]},
            {"type": "function_call_output", "output": "c"},
            {"role": "user", "content": [picture]},
        ],
    }
    assert _pictures(payload) == 3
    assert _pictures({"model": "m"}) == 0


def test_the_size_recorded_is_the_body_the_transport_sends() -> None:
    received = []

    def answer(request: httpx.Request) -> httpx.Response:
        received.append(len(request.content))
        return httpx.Response(200, json={})

    async def send() -> list[int | None]:
        transport = httpx.MockTransport(answer)
        hooks = {"request": [_record_sent]}
        async with httpx.AsyncClient(transport=transport, event_hooks=hooks) as client:
            body = {"input": "x" * 1000, "model": "m"}
            with sending() as sizes:
                await client.post("https://api.invalid/v1/responses", json=body)
            # Outside, nothing is recorded: the hook keeps sizes for the caller that asked.
            await client.post("https://api.invalid/v1/responses", json=body)
            return sizes

    sizes = asyncio.run(send())
    assert sizes == received[:1] and sizes[0] > len(json.dumps({"input": "x" * 1000}))
    assert len(received) == 2
