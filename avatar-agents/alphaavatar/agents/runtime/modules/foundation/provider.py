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
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from alphaavatar.agents.avatar.provider.base import LLMBase
from alphaavatar.agents.avatar.provider.factory import create_llm_model
from alphaavatar.agents.avatar.provider.schemas import (
    ProvidersConfig,
    ProviderTaskConfig,
    ProviderTraceConfig,
)
from alphaavatar.agents.avatar.provider.trace import ProviderTracer
from alphaavatar.core.cleanup import wait_for_cleanup

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.provider.gateway import ProviderGateway

T = TypeVar("T")


class _Closable(Protocol):
    async def aclose(self) -> None: ...


class ProviderService:
    """Own task models, requests and tracers for one Foundation instance."""

    def __init__(self) -> None:
        self._models: dict[str, LLMBase] = {}
        self._tracers: dict[str, ProviderTracer] = {}
        self._requests: set[asyncio.Task[Any]] = set()
        self._close_task: asyncio.Task[None] | None = None

    def _ensure_open(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Provider service is closing or closed")

    @staticmethod
    async def _close_resources(resources: tuple[_Closable, ...], *, phase: str) -> list[Exception]:
        async def close(resource: _Closable) -> None:
            await resource.aclose()

        results = await asyncio.gather(*(close(item) for item in resources), return_exceptions=True)
        errors: list[Exception] = []
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                error = RuntimeError(f"Provider {phase} cleanup was cancelled")
                error.__cause__ = result
                errors.append(error)
            elif isinstance(result, Exception):
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result
        return errors

    async def _close(self) -> None:
        requests = tuple(self._requests)
        for task in requests:
            task.cancel()
        await asyncio.gather(*requests, return_exceptions=True)
        self._requests.clear()

        errors = await self._close_resources(tuple(self._models.values()), phase="model")
        self._models.clear()
        errors.extend(await self._close_resources(tuple(self._tracers.values()), phase="trace"))
        self._tracers.clear()
        if errors:
            raise ExceptionGroup("Provider service cleanup failed", errors)

    def gateway(self, config: ProvidersConfig) -> ProviderGateway:
        from alphaavatar.agents.avatar.provider.gateway import ProviderGateway

        self._ensure_open()
        return ProviderGateway(config, service=self)

    def model(self, config: ProviderTaskConfig) -> LLMBase:
        self._ensure_open()
        snapshot = config.model_copy(deep=True)
        # Reject SDK objects and non-JSON configuration instead of hashing a masked repr.
        encoded = json.dumps(
            snapshot.model_dump(mode="python"),
            sort_keys=True,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        key = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if key not in self._models:
            self._models[key] = create_llm_model(snapshot)
        return self._models[key]

    def tracer(self, config: ProviderTraceConfig) -> ProviderTracer:
        self._ensure_open()
        key = config.model_dump_json()
        if key not in self._tracers:
            self._tracers[key] = ProviderTracer(config)
        return self._tracers[key]

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        self._ensure_open()

        async def invoke() -> T:
            return await operation()

        task = asyncio.create_task(invoke(), name="provider_request")
        self._requests.add(task)
        try:
            return await task
        finally:
            self._requests.discard(task)

    async def aclose(self) -> None:
        if asyncio.current_task() in self._requests:
            raise RuntimeError("A provider request cannot close its owning service")
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="provider_service_close")
        await wait_for_cleanup(self._close_task)
