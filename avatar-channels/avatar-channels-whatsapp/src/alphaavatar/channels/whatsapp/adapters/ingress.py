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

from livekit import rtc

from alphaavatar.agents.entrypoints.io.envelopes import InputEnvelope
from alphaavatar.agents.log import logger


class WhatsAppIngressAdapter:
    def __init__(
        self,
        *,
        room: rtc.Room,
        on_input: Callable[[InputEnvelope, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.room = room
        self.on_input = on_input

    def start(self) -> None:
        @self.room.on("data_received")
        def _on_data(packet: rtc.DataPacket) -> None:
            try:
                if packet.topic != "whatsapp.in":
                    return

                payload = json.loads(packet.data.decode("utf-8"))
                logger.info("WhatsAppIngressAdapter received whatsapp.in: %s", payload)

                envelope = InputEnvelope(
                    channel="whatsapp",
                    user_id=f"whatsapp:{payload.get('from', '')}",
                    session_id=f"whatsapp:{payload.get('chat_id', '')}",
                    room_name=self.room.name,
                    message_id=payload.get("message_id", ""),
                    modality="text",
                    text=payload.get("text", ""),
                    metadata=payload.get("meta", {}) or {},
                )

                asyncio.create_task(self.on_input(envelope, payload))
            except Exception:
                logger.exception("Failed to handle whatsapp.in packet")
