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
from collections.abc import Awaitable, Callable
from typing import Any

from livekit import api, rtc

from .log import logger


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
        participant_metadata: dict[str, Any] | None = None,
        on_agent_ready: Callable[[], Awaitable[None]] | None = None,
    ):
        self._on_outbound = on_outbound
        self._on_agent_ready = on_agent_ready

        self._url = livekit_url
        self._api_key = api_key
        self._api_secret = api_secret
        self._room_name = room_name
        self._identity = identity
        self._participant_metadata = participant_metadata or {}
        self._room: rtc.Room | None = None

        self._agent_ready = asyncio.Event()

    @property
    def is_ready(self) -> bool:
        return self._agent_ready.is_set()

    async def start(self) -> None:
        token_builder = (
            api.AccessToken(self._api_key, self._api_secret)
            .with_identity(self._identity)
            .with_grants(api.VideoGrants(room_join=True, room=self._room_name))
        )

        if self._participant_metadata:
            token_builder = token_builder.with_metadata(
                json.dumps(self._participant_metadata, ensure_ascii=False)
            )

        token = token_builder.to_jwt()

        room = rtc.Room()
        self._room = room

        @room.on("participant_connected")
        def _on_participant_connected(participant: rtc.RemoteParticipant):
            try:
                logger.info(
                    "Participant connected room=%s identity=%s",
                    self._room_name,
                    participant.identity,
                )
            except Exception:
                logger.exception("Failed in participant_connected handler")

        @room.on("data_received")
        def _on_data(packet: rtc.DataPacket):
            try:
                if packet.topic == "whatsapp.ready":
                    logger.info("Agent ready received room=%s", self._room_name)
                    if not self._agent_ready.is_set():
                        self._agent_ready.set()
                        if self._on_agent_ready is not None:
                            asyncio.create_task(self._on_agent_ready())
                    return

                if packet.topic != "whatsapp.out":
                    return

                payload = json.loads(packet.data.decode("utf-8"))
                asyncio.create_task(self._on_outbound(payload))
            except Exception:
                logger.exception("Failed to handle data_received")

        await room.connect(self._url, token)
        logger.info(
            "LiveKit connected room=%s identity=%s metadata=%s",
            self._room_name,
            self._identity,
            self._participant_metadata,
        )

    async def wait_until_ready(self, timeout: float = 10.0) -> bool:
        if self._agent_ready.is_set():
            return True

        try:
            await asyncio.wait_for(self._agent_ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "Timed out waiting for agent ready room=%s within %.1fs",
                self._room_name,
                timeout,
            )
            return False

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
