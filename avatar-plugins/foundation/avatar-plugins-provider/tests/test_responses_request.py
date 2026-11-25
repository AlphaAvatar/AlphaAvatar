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
import logging

import httpx
import pytest

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
    received, sizes = [], []

    def answer(request: httpx.Request) -> httpx.Response:
        received.append(len(request.content))
        return httpx.Response(200, json={})

    async def send() -> None:
        transport = httpx.MockTransport(answer)
        hooks = {"request": [_record_sent]}
        async with httpx.AsyncClient(transport=transport, event_hooks=hooks) as client:
            body = {"input": "x" * 1000, "model": "m"}
            with sending(sizes.append):
                await client.post("https://api.invalid/v1/responses", json=body)
            # Outside, nothing is recorded: the hook tells the caller that asked.
            await client.post("https://api.invalid/v1/responses", json=body)

    asyncio.run(send())
    assert sizes == received[:1] and sizes[0] > len(json.dumps({"input": "x" * 1000}))
    assert len(received) == 2


def test_each_attempt_is_logged_as_it_goes_to_the_transport_before_any_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Model request sent is when the encoded body reaches the transport, not when the
    response or the error comes back; a retry is logged as its own attempt."""
    from alphaavatar.agents.avatar.provider.enums import ModelRole
    from alphaavatar.agents.avatar.provider.errors import ModelRequestError
    from alphaavatar.agents.avatar.provider.schemas import (
        ModelInput,
        ModelInputMessage,
        ModelRequest,
        ModelTextPart,
    )
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig
    from alphaavatar.plugins.provider.openai.llms import client as module
    from alphaavatar.plugins.provider.openai.llms.responses import OpenAIResponsesLLM

    def logged() -> list[dict]:
        return [
            r.msg.fields
            for r in caplog.records
            if getattr(r.msg, "name", "") == "model.request_sent"
        ]

    seen = []  # The attempts already logged as each one reached the server

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append([fields["attempt"] for fields in logged()])
        return httpx.Response(500 if len(seen) == 1 else 401, json={"error": {"message": "no"}})

    import openai  # noqa: F401  # Its client subclasses httpx's: imported before the swap.

    class Answering(httpx.AsyncClient):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(transport=httpx.MockTransport(answer), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", Answering)
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    extra = {"api_key": "sk-fictional", "base_url": "https://api.invalid/v1", "max_retries": 1}
    llm = OpenAIResponsesLLM(ProviderTaskConfig(backend="openai", model="m", extra=extra))
    message = ModelInputMessage(id="m1", role=ModelRole.USER, parts=(ModelTextPart("Hello"),))
    request = ModelRequest(input=ModelInput(items=(message,)))

    async def run() -> None:
        try:
            async with llm.stream(request) as events:
                async for _ in events:
                    pass
        finally:
            await llm.aclose()

    with pytest.raises(ModelRequestError) as refused:
        asyncio.run(run())
    assert refused.value.code == "http_401"
    assert seen == [[1], [1, 2]]  # Each attempt logged before the server saw it.
    first, retry = logged()
    assert (first["request_id"], retry["request_id"]) == (request.request_id,) * 2
    assert first["request_bytes"] == retry["request_bytes"] > 0 and first["frame_count"] == 0


def test_prepared_its_client_and_responses_resource_load_off_the_loop_before_the_request(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """O-15: the SDK's first load, its client and its Responses resource, prepared in a thread
    while the session starts, the loop running on; the first request finds it ready."""
    import functools
    import threading
    import time

    import openai

    from alphaavatar.agents.avatar.provider.enums import ModelRole
    from alphaavatar.agents.avatar.provider.errors import ModelRequestError
    from alphaavatar.agents.avatar.provider.schemas import (
        ModelInput,
        ModelInputMessage,
        ModelRequest,
        ModelTextPart,
    )
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig
    from alphaavatar.plugins.provider.openai.llms import client as module
    from alphaavatar.plugins.provider.openai.llms.responses import OpenAIResponsesLLM

    loaded = []  # Whether each load ran on the event loop's thread
    real = openai.AsyncOpenAI.__dict__["responses"].func

    def slow(self: openai.AsyncOpenAI) -> object:  # A first import that takes its time
        time.sleep(0.3)
        loaded.append(threading.current_thread() is threading.main_thread())
        return real(self)

    resource = functools.cached_property(slow)
    resource.__set_name__(openai.AsyncOpenAI, "responses")
    monkeypatch.setattr(openai.AsyncOpenAI, "responses", resource)

    class Refusing(httpx.AsyncClient):
        def __init__(self, **kwargs: object) -> None:
            transport = httpx.MockTransport(lambda request: httpx.Response(401, json={}))
            super().__init__(transport=transport, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", Refusing)
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    extra = {"api_key": "sk-fictional", "base_url": "https://api.invalid/v1", "max_retries": 0}
    llm = OpenAIResponsesLLM(ProviderTaskConfig(backend="openai", model="m", extra=extra))
    message = ModelInputMessage(id="m1", role=ModelRole.USER, parts=(ModelTextPart("Hello"),))
    ticks: list[float] = []

    async def run() -> None:
        async def heartbeat() -> None:
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.01)

        beating = asyncio.create_task(heartbeat())
        try:
            llm.prepare()
            await asyncio.sleep(0.4)  # The session goes on starting.
            with pytest.raises(ModelRequestError):
                async with llm.stream(ModelRequest(input=ModelInput(items=(message,)))):
                    pass
        finally:
            beating.cancel()
            await llm.aclose()

    asyncio.run(run())
    assert loaded == [False]
    assert max(later - earlier for earlier, later in zip(ticks, ticks[1:], strict=False)) < 0.1
    (sent,) = [
        r.msg.fields for r in caplog.records if getattr(r.msg, "name", "") == "model.request_sent"
    ]
    assert sent["client_ms"] < 50  # Ready before the request: none of its own time
