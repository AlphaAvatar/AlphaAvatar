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
from abc import ABC, abstractmethod
from typing import Any

from alphaavatar.agents.status.schema import StatusEvent


class StatusRendererBase(ABC):
    def bind_engine(self, engine: Any) -> None:
        return None

    @abstractmethod
    async def render(self, event: StatusEvent) -> str | None: ...


class StatusPolicyBase(ABC):
    def bind_engine(self, engine: Any) -> None:
        return None

    def get_delay_sec(self, event: StatusEvent) -> float:
        return 0.0

    @abstractmethod
    def start_turn(self) -> None: ...

    @abstractmethod
    def should_emit(self, event: StatusEvent) -> bool: ...

    @abstractmethod
    def mark_emitted(self) -> None: ...


class StatusSinkBase(ABC):
    def bind_engine(self, engine: Any) -> None:
        return None

    @abstractmethod
    async def emit(self, event: StatusEvent, text: str | None) -> None: ...
