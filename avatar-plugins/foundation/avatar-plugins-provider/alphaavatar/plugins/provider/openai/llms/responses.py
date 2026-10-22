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
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from alphaavatar.agents.avatar.provider.base import StreamingLLMBase
from alphaavatar.agents.avatar.provider.enums import ModelMessagePhase
from alphaavatar.agents.avatar.provider.errors import (
    ModelCapabilityError,
    ModelProtocolError,
    ModelRefusalError,
    ModelRequestError,
)
from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionCall,
    ModelInput,
    ModelInputMessage,
    ModelRefusalPart,
    ModelRequest,
    ProviderModelResult,
    ProviderTaskConfig,
)
from alphaavatar.agents.avatar.provider.schemas.stream import ModelStreamEvent
from alphaavatar.core.cleanup import wait_for_cleanup

from ..adapters.responses import ResponsesAdapter, continuation_scope
from .client import ResponsesClient, observe_task
from .config import OpenAIClientConfig, ResponsesInputConfig
from .stream import ResponsesDecoder

T = TypeVar("T")


def _diagnostic(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key == "encrypted_content" else _diagnostic(item)
            for key, item in value.items()
            if not (value.get("type") == "reasoning" and key == "content")
        }
    if isinstance(value, list):
        return [_diagnostic(item) for item in value]
    return value


def _sdk_error(exc: Exception) -> ModelRequestError | None:
    from openai import APIConnectionError, APIStatusError, APITimeoutError

    if isinstance(exc, APITimeoutError | httpx.TimeoutException):
        return ModelRequestError("OpenAI request timed out", code="timeout", retryable=True)
    if isinstance(exc, APIConnectionError | httpx.TransportError):
        return ModelRequestError(
            "OpenAI connection failed", code="connection_error", retryable=True
        )
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        return ModelRequestError(
            f"OpenAI request failed with HTTP {status}",
            code=f"http_{status}",
            retryable=status in {408, 409, 429} or status >= 500,
        )
    return None


class OpenAIResponsesLLM(StreamingLLMBase):
    def __init__(self, config: ProviderTaskConfig) -> None:
        self._config = config.model_copy(deep=True)
        self._options = ResponsesInputConfig.model_validate(config.input_options)
        self._client = ResponsesClient(
            OpenAIClientConfig.model_validate(config.extra), timeout=config.timeout
        )
        self._preparations: set[asyncio.Task[Any]] = set()
        self._close_task: asyncio.Task[None] | None = None
        self.validate_input()

    def validate_input(self, *, require_input_adapter: bool = False) -> None:
        if self._close_task is not None:
            raise RuntimeError("Responses model is closing or closed")
        if self._config.provider.strip().lower() != "openai":
            raise ModelCapabilityError("The openai backend implements OpenAI Responses only")
        if self._config.input_adapter not in {None, "responses"}:
            raise ModelCapabilityError("The native backend uses its own Responses adapter")
        if not self._config.model.strip():
            raise ValueError("Responses model name cannot be empty")

    async def _prepare(self, operation: Callable[[], T]) -> T:
        task = asyncio.create_task(asyncio.to_thread(operation), name="responses_prepare")
        self._preparations.add(task)
        task.add_done_callback(self._preparations.discard)
        task.add_done_callback(observe_task)
        return await asyncio.shield(task)

    @asynccontextmanager
    async def _stream(
        self, request: ModelRequest
    ) -> AsyncIterator[tuple[AsyncIterator[ModelStreamEvent], ResponsesDecoder]]:
        self.validate_input()
        deadline = asyncio.get_running_loop().time() + self._config.timeout
        raw = None
        events = None
        try:
            async with asyncio.timeout_at(deadline):
                client = await self._client.get()
                adapter = ResponsesAdapter(
                    self._config,
                    self._options,
                    continuation_scope(self._client.scope, self._config.model),
                )
                payload = await self._prepare(lambda: adapter.encode(request))
                self.validate_input()
                try:
                    raw = await client.responses.create(**payload)
                except Exception as exc:
                    normalized = _sdk_error(exc)
                    if normalized is not None:
                        raise normalized from None
                    raise
            decoder = ResponsesDecoder(
                request_id=request.request_id,
                scope=continuation_scope(self._client.scope, self._config.model),
                options=self._options,
            )

            async def read() -> AsyncIterator[ModelStreamEvent]:
                iterator = raw.__aiter__()
                while True:
                    try:
                        async with asyncio.timeout_at(deadline):
                            try:
                                packet = await anext(iterator)
                            except StopAsyncIteration:
                                raise
                            except Exception as exc:
                                normalized = _sdk_error(exc)
                                if normalized is not None:
                                    raise normalized from None
                                raise
                    except StopAsyncIteration:
                        break
                    try:
                        event = packet.model_dump(mode="json", exclude_unset=True)
                        decoded = decoder.feed(event)
                    except (KeyError, TypeError, AttributeError, ValueError) as exc:
                        raise ModelProtocolError("Malformed Responses event fields") from exc
                    for output in decoded:
                        yield output
                    if decoder.completed is not None:
                        break
                decoder.finish()

            events = read()
            yield events, decoder
        finally:
            try:
                if events is not None:
                    await events.aclose()
            finally:
                if raw is not None:
                    await wait_for_cleanup(
                        asyncio.create_task(raw.close(), name="responses_stream_close")
                    )

    @asynccontextmanager
    async def stream(self, request: ModelRequest) -> AsyncIterator[AsyncIterator[ModelStreamEvent]]:
        async with self._stream(request) as (events, _):
            yield events

    async def ainvoke_structured(
        self, model_input: ModelInput, *, output_schema: type[BaseModel], include_raw: bool = False
    ) -> ProviderModelResult:
        request = ModelRequest(input=model_input, output_schema=output_schema, tool_choice="none")
        async with self._stream(request) as (events, decoder):
            async for _ in events:
                pass
            response = decoder.finish()
            if any(isinstance(item, ModelFunctionCall) for item in response.items):
                raise ModelProtocolError("Structured-only request returned a tool call")
            messages = [item for item in response.items if isinstance(item, ModelInputMessage)]
            if any(isinstance(part, ModelRefusalPart) for item in messages for part in item.parts):
                raise ModelRefusalError("Model refused the structured request")
            final = [item for item in messages if item.phase != ModelMessagePhase.COMMENTARY]
            if not final:
                raise ModelProtocolError("Structured request returned no answer message")
            text = "\n".join(item.text or "" for item in final)
            output = output_schema.model_validate_json(text)
            return ProviderModelResult(
                output=output,
                usage=response.usage,
                generation_id=response.response_id,
                raw_response=_diagnostic(decoder.raw_response) if include_raw else None,
            )

    async def _close(self) -> None:
        await asyncio.gather(*tuple(self._preparations), return_exceptions=True)
        await self._client.aclose()

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="responses_model_close")
        await wait_for_cleanup(self._close_task)
