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
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime import AvatarRuntime, SessionRuntime
from alphaavatar.agents.runtime.capability import AvatarCapability
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.core.perception import PerceptionRuntime

if TYPE_CHECKING:
    from .base import PersonaBase


class PersonaProcessorBase(ABC):
    capabilities: tuple[AvatarCapability, ...] = ()

    def __init__(self, *, runtime: AvatarRuntime, persona: PersonaBase) -> None:
        self._runtime = runtime
        self._persona = persona
        self._started = False
        self._lifecycle_lock = asyncio.Lock()

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def runtime(self) -> AvatarRuntime:
        return self._runtime

    @property
    def persona(self) -> PersonaBase:
        return self._persona

    @property
    def session_runtime(self) -> SessionRuntime:
        return self._runtime.session

    @property
    def perception_runtime(self) -> PerceptionRuntime:
        return self._runtime.perception

    @property
    def inference_executor(self) -> InferenceExecutor:
        return self._runtime.inference

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._started:
                return

            try:
                await self._start()
            except BaseException:
                try:
                    await self._stop(finalize=False)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Failed to rollback Persona processor name=%s",
                        self.name,
                    )
                raise

            self._started = True

    async def stop(self, *, finalize: bool = True) -> None:
        async with self._lifecycle_lock:
            if not self._started:
                return

            try:
                await self._stop(finalize=finalize)
            finally:
                self._started = False

    @abstractmethod
    async def _start(self) -> None: ...

    @abstractmethod
    async def _stop(self, *, finalize: bool) -> None: ...
