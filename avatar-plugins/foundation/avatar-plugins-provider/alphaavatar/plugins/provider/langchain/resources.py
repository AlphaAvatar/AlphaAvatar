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
from collections.abc import Awaitable, Callable

from alphaavatar.core.cleanup import wait_for_cleanup


class ModelResources:
    """Callbacks are registered during one initialization; only the owner closes them."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[], Awaitable[None]]] = []
        self._close_task: asyncio.Task[None] | None = None

    def add_sync(self, close: Callable[[], None]) -> None:
        async def cleanup() -> None:
            await asyncio.to_thread(close)

        self._callbacks.append(cleanup)

    def add_async(self, close: Callable[[], Awaitable[None]]) -> None:
        self._callbacks.append(close)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="provider_clients_close")
        await wait_for_cleanup(self._close_task)

    async def _close(self) -> None:
        callbacks, self._callbacks = self._callbacks, []
        errors: list[Exception] = []
        for close in reversed(callbacks):
            try:
                await close()
            except asyncio.CancelledError as exc:
                error = RuntimeError("Provider client cleanup was cancelled")
                error.__cause__ = exc
                errors.append(error)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("Provider client cleanup failed", errors)
