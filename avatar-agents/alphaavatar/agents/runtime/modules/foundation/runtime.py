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

from alphaavatar.core.cleanup import wait_for_cleanup

from .provider import ProviderService
from .voice import VoiceService


class FoundationRuntime:
    """Own shared services; consumers must finish before this runtime is closed."""

    def __init__(
        self, *, voice: VoiceService | None = None, provider: ProviderService | None = None
    ) -> None:
        self._voice = voice if voice is not None else VoiceService()
        self._provider = provider if provider is not None else ProviderService()
        self._close_task: asyncio.Task[None] | None = None

    @property
    def voice(self) -> VoiceService:
        return self._voice

    @property
    def provider(self) -> ProviderService:
        return self._provider

    async def _close(self) -> None:
        async def close(service: ProviderService | VoiceService) -> None:
            await service.aclose()

        results = await asyncio.gather(
            close(self._provider), close(self._voice), return_exceptions=True
        )
        errors: list[Exception] = []
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                error = RuntimeError("Foundation service cleanup was cancelled")
                error.__cause__ = result
                errors.append(error)
            elif isinstance(result, Exception):
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result
        if errors:
            raise ExceptionGroup("Foundation cleanup failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="foundation_close")
        await wait_for_cleanup(self._close_task)
