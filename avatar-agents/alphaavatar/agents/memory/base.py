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
from collections.abc import Sequence
from typing import TYPE_CHECKING

from alphaavatar.agents.runtime.plugin import AvatarRuntimePlugin

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.provider.schemas.model_input import ModelInputItem
    from alphaavatar.agents.runtime.capability import AvatarCapabilityRegistry


class MemoryBase(AvatarRuntimePlugin):
    @property
    @abstractmethod
    def capability_registry(self) -> AvatarCapabilityRegistry: ...

    @property
    @abstractmethod
    def root_context_id(self) -> str: ...

    @property
    @abstractmethod
    def memory_content(self) -> str: ...

    @abstractmethod
    def add_messages(self, *, context_id: str, items: Sequence[ModelInputItem]) -> None:
        """Accept native assistant/tool records atomically into the extraction buffer.

        This is local acceptance, not a durable write or proof of user delivery.
        User input is consumed separately from committed TurnSnapshots.
        """
