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
from typing import TYPE_CHECKING

from alphaavatar.core.lifecycle import LifecycleComponent

if TYPE_CHECKING:
    from alphaavatar.agents.runtime.capability import AvatarCapabilityRegistry
    from alphaavatar.core.turn.schemas import TurnSnapshot


class MemoryBase(LifecycleComponent):
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
    def content_for(self, snapshot: TurnSnapshot) -> str:
        """Project shared memory for the actual actors of one committed Turn."""
