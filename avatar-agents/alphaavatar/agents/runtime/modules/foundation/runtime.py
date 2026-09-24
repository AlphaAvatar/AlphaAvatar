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

from ...cleanup import wait_for_cleanup
from .voice import VoiceService


class FoundationRuntime:
    """Own foundation services without importing concrete plugins or configuration."""

    def __init__(self, *, voice: VoiceService | None = None) -> None:
        self._voice = voice if voice is not None else VoiceService()
        self._close_task: asyncio.Task[None] | None = None

    @property
    def voice(self) -> VoiceService:
        return self._voice

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._voice.aclose(), name="foundation_close")
        await wait_for_cleanup(self._close_task)
