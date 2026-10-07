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

from alphaavatar.agents.avatar.provider.schemas import ModelInput
from alphaavatar.agents.avatar.provider.schemas.model_input import ModelInputItem

from .schemas import ContextPrepareRequest

if TYPE_CHECKING:
    from alphaavatar.agents.memory import MemoryBase
    from alphaavatar.agents.persona import PersonaBase


class ContextManager(ABC):
    """One public context API. Captured inputs are execution-owned immutable values."""

    @property
    @abstractmethod
    def initial_instructions(self) -> str: ...

    @abstractmethod
    def bind_sources(self, *, memory: MemoryBase, persona: PersonaBase) -> None:
        """Borrow the Engine's state sources; do not own or stop those processors."""

    @abstractmethod
    async def prepare(self, request: ContextPrepareRequest) -> ModelInput:
        """Wait for the committed turn, then capture state and query-static contributions once."""

    @abstractmethod
    def build(
        self, prefix: ModelInput, *, continuation: tuple[ModelInputItem, ...] = ()
    ) -> ModelInput:
        """Compose a request from a captured prefix and canonical execution records only."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close after consumers stop; never close the borrowed AvatarRuntime."""
