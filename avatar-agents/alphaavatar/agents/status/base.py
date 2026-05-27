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
import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from alphaavatar.agents.log import logger
from alphaavatar.agents.status.schema import StatusEvent

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.engine import AvatarEngine


class StatusRendererBase(ABC):
    def bind_engine(self, engine: AvatarEngine | None) -> None:
        return None

    @abstractmethod
    async def render(self, event: StatusEvent) -> str | None: ...


class StatusPolicyBase(ABC):
    def bind_engine(self, engine: AvatarEngine | None) -> None:
        return None

    def get_delay_sec(self, event: StatusEvent) -> float:
        return 0.0

    @abstractmethod
    def start_turn(self) -> None: ...

    @abstractmethod
    def should_emit(self, event: StatusEvent) -> bool: ...

    @abstractmethod
    def mark_emitted(self, event: StatusEvent | None = None) -> None: ...


class StatusSinkBase(ABC):
    def bind_engine(self, engine: AvatarEngine | None) -> None:
        return None

    @abstractmethod
    async def emit(self, event: StatusEvent, text: str | None) -> None: ...


class LiveKitDataPublisherMixin:
    _engine: AvatarEngine | None
    reliable: bool

    def _get_local_participant(self):
        if self._engine is None:
            return None

        room = getattr(self._engine, "livekit_room", None)
        if room is None:
            logger.debug("Status sink skipped because engine.livekit_room is unavailable.")
            return None

        return getattr(room, "local_participant", None)

    async def _publish_data(self, local_participant, payload: dict[str, Any], *, topic: str):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        publish_data = getattr(local_participant, "publish_data", None)

        if publish_data is None:
            logger.debug("LiveKit local_participant has no publish_data method.")
            return

        result = publish_data(
            data,
            reliable=self.reliable,
            topic=topic,
        )

        if asyncio.iscoroutine(result):
            await result
