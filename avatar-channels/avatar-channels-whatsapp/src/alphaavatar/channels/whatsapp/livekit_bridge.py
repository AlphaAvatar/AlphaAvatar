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
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from livekit import api, rtc

logger = logging.getLogger("alphaavatar.whatsapp.livekit")


class LiveKitBridge:
    def __init__(
        self,
        *,
        on_outbound: Callable[[dict[str, Any]], Awaitable[None]],
        livekit_url: str,
        api_key: str,
        api_secret: str,
        room_name: str,
        identity: str = "whatsapp-bridge",
    ):
        self._on_outbound = on_outbound
        self._url = livekit_url
        self._api_key = api_key
        self._api_secret = api_secret
        self._room_name = room_name
        self._identity = identity
        self._room: rtc.Room | None = None

    async def start(self) -> None:
        token = (
            api.AccessToken(self._api_key, self._api_secret)
            .with_identity(self._identity)
            .with_grants(api.VideoGrants(room_join=True, room=self._room_name))
            .to_jwt()
        )

        room = rtc.Room()
        self._room = room

        @room.on("data_received")
        def _on_data(packet: rtc.DataPacket):
            # LiveKit -> Core -> Driver
            try:
                if packet.topic != "whatsapp.out":
                    return

                payload = json.loads(packet.data.decode("utf-8"))
                asyncio.create_task(self._on_outbound(payload))
            except Exception:
                logger.exception("Failed to handle data_received")

        await room.connect(self._url, token)
        logger.info("LiveKit connected room=%s identity=%s", self._room_name, self._identity)

    async def publish_inbound(self, payload: dict[str, Any]) -> None:
        if not self._room:
            raise RuntimeError("LiveKitBridge not started")

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await self._room.local_participant.publish_data(
            data,
            topic="whatsapp.in",
            reliable=True,
        )

    async def aclose(self) -> None:
        if self._room:
            await self._room.disconnect()
            self._room = None
