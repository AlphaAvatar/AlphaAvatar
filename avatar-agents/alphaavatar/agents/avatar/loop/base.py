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

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from .schemas import LoopIdentity, LoopRequest, LoopResult, ToolCallContext

ToolAuthorizer = Callable[[ToolCallContext], Awaitable[bool]]


class LoopHandle(ABC):
    @property
    @abstractmethod
    def identity(self) -> LoopIdentity: ...

    @abstractmethod
    def cancel(self, *, reason: str = "interrupted") -> None: ...

    @abstractmethod
    async def wait(self) -> LoopResult:
        """Cancelling a waiter does not abandon the owned execution."""

    @abstractmethod
    async def aclose(self) -> None: ...


class Loop(ABC):
    @property
    @abstractmethod
    def ready(self) -> bool: ...

    @abstractmethod
    async def initialize(self) -> None:
        """Resolve shared services after Foundation binding."""

    @abstractmethod
    async def submit(
        self,
        request: LoopRequest,
        *,
        authorize: ToolAuthorizer | None = None,
    ) -> LoopHandle:
        """Accept quickly; publish execution facts, model records and delivery through Runtime."""

    @abstractmethod
    def interrupt(self, *, run_id: str | None = None, reason: str = "interrupted") -> None: ...

    @abstractmethod
    async def aclose(self) -> None: ...
