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
import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import httpx

from alphaavatar.agents.avatar.provider.errors import ModelRequestError
from alphaavatar.core.cleanup import wait_for_cleanup

from .config import OpenAIClientConfig

# Who hears of each request body as it goes to the transport, in this context: called with
# the body's size, once per attempt.
_SENT: ContextVar[Callable[[int | None], None] | None] = ContextVar("responses_sent", default=None)


async def _record_sent(request: httpx.Request) -> None:
    if (sent := _SENT.get()) is not None:
        try:
            size = len(request.content)  # The body as the SDK encoded it, sent as is.
        except httpx.RequestNotRead:
            size = None  # A streamed body: its size is not known up front.
        sent(size)


@contextmanager
def sending(sent: Callable[[int | None], None]) -> Iterator[None]:
    """``sent`` called as each request body within goes to the transport, with its size: once
    per attempt, the SDK's retries too, before the server sees it."""
    token = _SENT.set(sent)
    try:
        yield
    finally:
        _SENT.reset(token)


def observe_task(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


class ResponsesClient:
    """One owned async transport. Cancelling a request never closes this shared client."""

    def __init__(self, config: OpenAIClientConfig, *, timeout: float) -> None:
        self._config = config
        self._timeout = timeout
        self._transport: httpx.AsyncClient | None = None
        self._client: Any = None
        self._scope: str | None = None
        self._init_task: asyncio.Task[Any] | None = None
        self._close_task: asyncio.Task[None] | None = None

    @property
    def scope(self) -> str:
        if self._scope is None:
            raise RuntimeError("Responses client has not been initialized")
        return self._scope

    def _ensure_open(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Responses client is closing or closed")

    def _build(self) -> Any:
        from openai import AsyncOpenAI

        config = self._config
        key = config.api_key.get_secret_value() if config.api_key else os.getenv(config.api_key_env)
        if not key:
            raise ModelRequestError("OpenAI API key is missing", code="missing_api_key")
        identity = [config.base_url, config.organization, config.project, key]
        self._scope = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        self._transport = httpx.AsyncClient(
            proxy=config.proxy, timeout=self._timeout, event_hooks={"request": [_record_sent]}
        )
        self._client = AsyncOpenAI(
            api_key=key,
            base_url=config.base_url,
            organization=config.organization,
            project=config.project,
            max_retries=config.max_retries,
            timeout=self._timeout,
            http_client=self._transport,
        )
        # The SDK imports its Responses resource on first use, about 0.1 s (O-15): here, in
        # this thread, not on the event loop within the first request.
        _ = self._client.responses
        return self._client

    async def _initialize(self) -> Any:
        try:
            return await asyncio.to_thread(self._build)
        except BaseException:
            if self._transport is not None:
                await self._transport.aclose()
            raise

    def prepare(self) -> None:
        """Start building the client, off the event loop, before a request needs it; a build
        that fails says so to the request that asks for it."""
        self._ensure_open()
        if self._init_task is None:
            self._init_task = asyncio.create_task(self._initialize(), name="responses_client_init")
            self._init_task.add_done_callback(observe_task)

    async def get(self) -> Any:
        self.prepare()
        client = await asyncio.shield(self._init_task)
        self._ensure_open()
        return client

    async def _close(self) -> None:
        if self._init_task is not None:
            await asyncio.gather(self._init_task, return_exceptions=True)
        try:
            if self._client is not None:
                await self._client.close()
        finally:
            if self._transport is not None and not self._transport.is_closed:
                await self._transport.aclose()
            self._client = None

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="responses_client_close")
        await wait_for_cleanup(self._close_task)
