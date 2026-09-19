# Copyright 2025 AlphaAvatar project
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

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from alphaavatar.agents.plugin import AvatarRuntimePlugin

if TYPE_CHECKING:
    from livekit.agents.llm import ChatItem

    from alphaavatar.agents.runtime import SessionRuntime
    from alphaavatar.agents.runtime.capability import AvatarCapability, AvatarCapabilityRegistry

    from .processor import MemoryProcessorBase
    from .schemas import MemoryItem


class MemoryBase(AvatarRuntimePlugin):
    @property
    @abstractmethod
    def capabilities(self) -> tuple[AvatarCapability, ...]: ...

    @property
    @abstractmethod
    def capability_registry(self) -> AvatarCapabilityRegistry: ...

    @property
    @abstractmethod
    def processors(self) -> tuple[MemoryProcessorBase, ...]: ...

    @property
    @abstractmethod
    def session_runtime(self) -> SessionRuntime: ...

    @property
    @abstractmethod
    def root_context_id(self) -> str: ...

    @property
    @abstractmethod
    def memory_content(self) -> str: ...

    @property
    @abstractmethod
    def memory_items(self) -> list[MemoryItem]: ...

    @abstractmethod
    def add_message(self, *, context_id: str, chat_item: ChatItem) -> None: ...

    @abstractmethod
    async def update(self, *, context_id: str | None = None) -> None: ...

    @abstractmethod
    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any: ...
