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
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from .dispatch import create_agent_dispatch_for_room
from .livekit_bridge import LiveKitBridge
from .schema.settings import WhatsAppBridgeSettings

logger = logging.getLogger("alphaavatar.whatsapp.room_manager")


def make_room_name(chat_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", chat_id)
    return f"wa_{safe}"


@dataclass
class ManagedRoom:
    chat_id: str
    room_name: str
    bridge: LiveKitBridge
    last_active_ts: float


class WhatsAppRoomManager:
    def __init__(self, *, settings: WhatsAppBridgeSettings, on_outbound):
        self.settings = settings
        self.on_outbound = on_outbound
        self.rooms: dict[str, ManagedRoom] = {}
        self.idle_timeout_sec = int(os.environ.get("WHATSAPP_IDLE_TIMEOUT_SEC", "900"))  # 15 min
        self._cleanup_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("WhatsAppRoomManager started idle_timeout=%ss", self.idle_timeout_sec)

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None

        for room in list(self.rooms.values()):
            await room.bridge.aclose()
        self.rooms.clear()

    async def ensure_room(self, chat_id: str) -> ManagedRoom:
        async with self._lock:
            existing = self.rooms.get(chat_id)
            if existing:
                existing.last_active_ts = time.time()
                return existing

            room_name = make_room_name(chat_id)

            bridge = LiveKitBridge(
                on_outbound=self.on_outbound,
                livekit_url=self.settings.livekit_url,
                api_key=self.settings.livekit_api_key,
                api_secret=self.settings.livekit_api_secret,
                room_name=room_name,
                identity=f"{self.settings.identity}-{room_name}",
            )
            await bridge.start()

            agent_name = os.environ.get("AVATAR_NAME", "").strip()
            if agent_name:
                await create_agent_dispatch_for_room(room_name, agent_name=agent_name)
                logger.info("Dispatched agent room=%s agent_name=%s", room_name, agent_name)
            else:
                logger.warning("AVATAR_NAME is empty; skip dispatch for room=%s", room_name)

            managed = ManagedRoom(
                chat_id=chat_id,
                room_name=room_name,
                bridge=bridge,
                last_active_ts=time.time(),
            )
            self.rooms[chat_id] = managed
            logger.info("Created WhatsApp room chat_id=%s room=%s", chat_id, room_name)
            return managed

    async def publish_inbound(self, chat_id: str, payload: dict[str, Any]) -> None:
        room = await self.ensure_room(chat_id)
        room.last_active_ts = time.time()
        await room.bridge.publish_inbound(payload)

    async def _cleanup_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                now = time.time()

                expired: list[str] = []
                for chat_id, room in self.rooms.items():
                    if now - room.last_active_ts >= self.idle_timeout_sec:
                        expired.append(chat_id)

                for chat_id in expired:
                    room = self.rooms.pop(chat_id, None)
                    if room:
                        logger.info(
                            "Closing idle WhatsApp room chat_id=%s room=%s idle_for=%.1fs",
                            chat_id,
                            room.room_name,
                            now - room.last_active_ts,
                        )
                        await room.bridge.aclose()
        except asyncio.CancelledError:
            logger.info("WhatsAppRoomManager cleanup loop cancelled")
