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
from typing import TYPE_CHECKING

from alphaavatar.core.lifecycle import LifecycleComponent

from .schemas import SessionContext, SessionEnd, SessionRequest

if TYPE_CHECKING:
    from alphaavatar.host.configs.application import ApplicationConfig
    from alphaavatar.host.execution.execution import HostExecution
    from alphaavatar.host.execution.manager import ExecutionManager

    from .attachment import SessionAttachment


class SessionConnection(LifecycleComponent):
    @property
    @abstractmethod
    def context(self) -> SessionContext: ...

    @abstractmethod
    async def wait_ended(self) -> SessionEnd: ...


class SessionBackend(ABC):
    @property
    @abstractmethod
    def ready(self) -> bool: ...

    @abstractmethod
    async def serve(self, manager: ExecutionManager, *, agent_name: str) -> None: ...

    @abstractmethod
    async def stop_accepting(self) -> None: ...

    @abstractmethod
    async def aclose(self) -> None: ...

    @abstractmethod
    def connection(self, request: SessionRequest) -> SessionConnection: ...

    @abstractmethod
    async def attachment(
        self, *, connection: SessionConnection, execution: HostExecution, config: ApplicationConfig
    ) -> SessionAttachment: ...
