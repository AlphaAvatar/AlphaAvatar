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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from math import isfinite
from typing import Any

from pydantic import BaseModel

from .decorator import validate_handler
from .schema import AvatarCapability

Arguments = Mapping[str, Any] | BaseModel | None
Handler = Callable[[Any], Awaitable[Any]]


class AvatarCapabilityRegistry:
    def __init__(self, *sources: object) -> None:
        self._bindings: dict[str, tuple[AvatarCapability, Handler | None]] = {}
        self._aliases: dict[str, str] = {}
        if sources:
            self.collect(*sources)

    @property
    def capabilities(self) -> tuple[AvatarCapability, ...]:
        return tuple(capability for capability, _ in self._bindings.values())

    def register(self, capability: AvatarCapability, handler: Handler | None = None) -> None:
        if not isinstance(capability, AvatarCapability):
            raise TypeError("Expected AvatarCapability")
        if capability.callable:
            validate_handler(handler)
        elif handler is not None:
            raise TypeError("A description-only capability must not bind a handler")

        existing = self._bindings.get(capability.id)
        if existing is not None:
            if existing[0] is capability and existing[1] == handler:
                return
            raise ValueError(f"Capability already registered: {capability.id}")

        aliases = {capability.id, capability.tool_name}
        for alias in aliases:
            if alias in self._aliases:
                raise ValueError(f"Capability name collision: {alias}")

        self._bindings[capability.id] = (capability, handler)
        self._aliases.update(dict.fromkeys(aliases, capability.id))

    def collect(self, *sources: object) -> None:
        staged = AvatarCapabilityRegistry()
        staged._bindings = self._bindings.copy()
        staged._aliases = self._aliases.copy()

        for source in sources:
            if isinstance(source, type):
                raise TypeError("Collect capability instances, not classes")
            registry = (
                source
                if isinstance(source, AvatarCapabilityRegistry)
                else getattr(
                    source,
                    "capability_registry",
                    None,
                )
            )
            if registry is not None:
                if not isinstance(registry, AvatarCapabilityRegistry):
                    raise TypeError("capability_registry must be AvatarCapabilityRegistry")
                for capability, handler in registry._bindings.values():
                    staged.register(capability, handler)
            elif isinstance(source, AvatarCapability):
                staged.register(source)
            else:
                for capability in getattr(source, "capabilities", ()):
                    handler = getattr(source, "invoke", None) if capability.callable else None
                    staged.register(capability, handler)

        self._bindings, self._aliases = staged._bindings, staged._aliases

    def _prepare(self, name: str, arguments: Arguments) -> tuple[Handler, Any]:
        if not isinstance(name, str):
            raise TypeError("Capability id must be a string")
        capability_id = self._aliases.get(name.strip())
        if capability_id is None:
            raise KeyError(f"Unknown capability: {name}")
        capability, handler = self._bindings[capability_id]
        if handler is None:
            raise TypeError(
                f"Capability is description-only and cannot be invoked: {capability.id}"
            )
        return handler, capability.parse(arguments)

    @staticmethod
    async def _execute(handler: Handler, request: Any, timeout: float | None) -> Any:
        if timeout is not None and (not isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be finite and positive")
        async with asyncio.timeout(timeout):
            return await handler(request)

    async def invoke(
        self, name: str, arguments: Arguments = None, *, timeout: float | None = None
    ) -> Any:
        handler, request = self._prepare(name, arguments)
        return await self._execute(handler, request, timeout)

    async def invoke_many(
        self,
        calls: Sequence[tuple[str, Arguments]],
        *,
        concurrency: int = 1,
        timeout: float | None = None,
    ) -> list[Any]:
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
            raise ValueError("concurrency must be a positive integer")
        prepared = [self._prepare(name, arguments) for name, arguments in calls]
        if concurrency == 1:
            return [await self._execute(handler, request, timeout) for handler, request in prepared]

        results: list[Any] = [None] * len(prepared)
        pending = iter(enumerate(prepared))

        async def worker() -> None:
            for index, (handler, request) in pending:
                results[index] = await self._execute(handler, request, timeout)

        async with asyncio.TaskGroup() as group:
            for _ in range(min(concurrency, len(prepared))):
                group.create_task(worker())
        return results
