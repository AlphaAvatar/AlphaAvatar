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

from alphaavatar.agents.avatar.context import ContextManager
from alphaavatar.agents.avatar.loop import Loop
from alphaavatar.agents.avatar.voice import VoiceBundle
from alphaavatar.core.cleanup import wait_for_cleanup

from .provider import ProviderService


class FoundationRuntime:
    """Shared owners; Engine/Loop consumers must stop before Foundation closes."""

    def __init__(
        self,
        *,
        context: ContextManager,
        loop: Loop,
        voice: VoiceBundle | None = None,
        provider: ProviderService | None = None,
    ) -> None:
        self._context = context
        self._loop = loop

        self._voice = voice if voice is not None else VoiceBundle()
        self._provider = provider if provider is not None else ProviderService()

        self._close_task: asyncio.Task[None] | None = None

    @property
    def context(self) -> ContextManager:
        return self._context

    @property
    def loop(self) -> Loop:
        return self._loop

    @property
    def voice(self) -> VoiceBundle:
        return self._voice

    @property
    def provider(self) -> ProviderService:
        return self._provider

    async def _close(self) -> None:
        errors: list[Exception] = []

        async def close(service) -> None:
            try:
                await service.aclose()
            except asyncio.CancelledError as exc:
                error = RuntimeError("Foundation service cleanup was cancelled")
                error.__cause__ = exc
                errors.append(error)
            except Exception as exc:
                errors.append(exc)

        if self._context is not None:
            await close(self._context)

        await asyncio.gather(close(self._provider), close(self._voice))
        if errors:
            raise ExceptionGroup("Foundation cleanup failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="foundation_close")

        await wait_for_cleanup(self._close_task)
