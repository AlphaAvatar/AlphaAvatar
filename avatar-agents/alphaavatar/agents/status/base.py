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

from alphaavatar.agents.status.schema import StatusEvent


class StatusRendererBase(ABC):
    @abstractmethod
    async def render(
        self,
        event: StatusEvent,
    ) -> str | None:
        raise NotImplementedError


class StatusPolicyBase(ABC):
    def get_delay_sec(
        self,
        event: StatusEvent,
    ) -> float:
        return 0.0

    @abstractmethod
    def start_turn(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def should_emit(
        self,
        event: StatusEvent,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def mark_emitted(
        self,
        event: StatusEvent | None = None,
    ) -> None:
        raise NotImplementedError


class StatusSinkBase(ABC):
    """
    Semantic status delivery interface.

    Concrete sinks decide whether a status is logged, published to the output
    stream, converted into transient speech, or sent elsewhere.
    """

    async def start_turn(
        self,
        *,
        turn_id: str,
    ) -> None:
        """Reset sink state and stop stale output from earlier turns."""
        return None

    @abstractmethod
    async def emit(
        self,
        event: StatusEvent,
        text: str | None,
    ) -> None:
        raise NotImplementedError
