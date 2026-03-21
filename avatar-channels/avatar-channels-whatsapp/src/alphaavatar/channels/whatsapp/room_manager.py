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
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .dispatch import create_agent_dispatch_for_room
from .livekit_bridge import LiveKitBridge
from .log import logger
from .schema.settings import WhatsAppBridgeSettings


def make_room_name(chat_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", chat_id)
    return f"wa_{safe}"


def normalize_sender_id(value: str) -> str:
    # 143744686940161@lid -> 143744686940161
    # 9715xxxxxxx@s.whatsapp.net -> 9715xxxxxxx
    return (value or "").split("@")[0]


def make_user_id(sender_id: str) -> str:
    return f"whatsapp:{sender_id}"


def make_session_id(user_id: str) -> str:
    return f"{user_id}:whatsapp:{uuid4().hex}"


@dataclass
class ManagedRoom:
    chat_id: str
    room_name: str
    user_id: str
    session_id: str
    bridge: LiveKitBridge
    last_active_ts: float
    pending_messages: list[dict[str, Any]] = field(default_factory=list)
    warmup_task: asyncio.Task | None = None


class WhatsAppRoomManager:
    def __init__(self, *, settings: WhatsAppBridgeSettings, on_outbound):
        self.settings = settings
        self.on_outbound = on_outbound
        self.rooms: dict[str, ManagedRoom] = {}
        self.idle_timeout_sec = int(os.environ.get("WHATSAPP_IDLE_TIMEOUT_SEC", "900"))
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
            if room.warmup_task and not room.warmup_task.done():
                room.warmup_task.cancel()
            await room.bridge.aclose()

        self.rooms.clear()

    async def ensure_room(
        self,
        *,
        chat_id: str,
        user_id: str,
    ) -> tuple[ManagedRoom, bool]:
        async with self._lock:
            existing = self.rooms.get(chat_id)
            if existing:
                existing.last_active_ts = time.time()
                return existing, False

            room_name = make_room_name(chat_id)
            session_id = make_session_id(user_id)

            participant_metadata = {
                "channel": "whatsapp",
                "room_type": "whatsapp",
                "user_id": user_id,
                "session_id": session_id,
                "chat_id": chat_id,
            }

            async def _on_agent_ready() -> None:
                await self._flush_pending_messages(chat_id)

            bridge = LiveKitBridge(
                on_outbound=self.on_outbound,
                on_agent_ready=_on_agent_ready,
                livekit_url=self.settings.livekit_url,
                api_key=self.settings.livekit_api_key,
                api_secret=self.settings.livekit_api_secret,
                room_name=room_name,
                identity=f"{self.settings.identity}-{room_name}",
                participant_metadata=participant_metadata,
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
                user_id=user_id,
                session_id=session_id,
                bridge=bridge,
                last_active_ts=time.time(),
            )
            self.rooms[chat_id] = managed

            managed.warmup_task = asyncio.create_task(
                self._warmup_room(chat_id=chat_id, room=managed)
            )

            logger.info(
                "Created WhatsApp room chat_id=%s room=%s user_id=%s session_id=%s",
                chat_id,
                room_name,
                user_id,
                session_id,
            )
            return managed, True

    async def publish_inbound(self, *, chat_id: str, payload: dict[str, Any]) -> None:
        raw_from = payload.get("from", "")
        sender_id = normalize_sender_id(raw_from)
        user_id = make_user_id(sender_id)

        room, is_new = await self.ensure_room(
            chat_id=chat_id,
            user_id=user_id,
        )
        room.last_active_ts = time.time()

        payload["user_id"] = room.user_id
        payload["session_id"] = room.session_id

        if room.bridge.is_ready:
            await room.bridge.publish_inbound(payload)
            return

        room.pending_messages.append(payload)

        logger.info(
            "Buffered inbound message chat_id=%s room=%s is_new=%s pending=%d",
            chat_id,
            room.room_name,
            is_new,
            len(room.pending_messages),
        )

    async def _warmup_room(self, *, chat_id: str, room: ManagedRoom) -> None:
        try:
            ready = await room.bridge.wait_until_ready(timeout=15.0)
            logger.info(
                "Room warmup complete chat_id=%s room=%s ready=%s",
                chat_id,
                room.room_name,
                ready,
            )

            if ready:
                await self._flush_pending_messages(chat_id)
            else:
                logger.warning(
                    "Agent still not ready after warmup chat_id=%s room=%s pending=%d",
                    chat_id,
                    room.room_name,
                    len(room.pending_messages),
                )
        except asyncio.CancelledError:
            logger.info("Warmup task cancelled chat_id=%s room=%s", chat_id, room.room_name)
        except Exception:
            logger.exception("Warmup task failed chat_id=%s room=%s", chat_id, room.room_name)

    async def _flush_pending_messages(self, chat_id: str) -> None:
        room = self.rooms.get(chat_id)
        if not room:
            return

        if not room.bridge.is_ready:
            return

        if not room.pending_messages:
            return

        pending = list(room.pending_messages)
        room.pending_messages.clear()

        logger.info(
            "Flushing pending messages chat_id=%s room=%s count=%d",
            chat_id,
            room.room_name,
            len(pending),
        )

        for payload in pending:
            try:
                await room.bridge.publish_inbound(payload)
            except Exception:
                logger.exception(
                    "Failed to flush pending inbound chat_id=%s room=%s",
                    chat_id,
                    room.room_name,
                )

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
                            "Closing idle WhatsApp room chat_id=%s room=%s user_id=%s session_id=%s idle_for=%.1fs",
                            chat_id,
                            room.room_name,
                            room.user_id,
                            room.session_id,
                            now - room.last_active_ts,
                        )
                        if room.warmup_task and not room.warmup_task.done():
                            room.warmup_task.cancel()
                        await room.bridge.aclose()
        except asyncio.CancelledError:
            logger.info("WhatsAppRoomManager cleanup loop cancelled")
