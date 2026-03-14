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

import json
from typing import Any

from livekit import rtc

from alphaavatar.agents.entrypoints.io.envelopes import OutputEnvelope
from alphaavatar.agents.log import logger


class WhatsAppEgressAdapter:
    def __init__(self, *, room: rtc.Room) -> None:
        self.room = room

    async def send_text(self, envelope: OutputEnvelope, *, raw_inbound: dict[str, Any]) -> None:
        payload = {
            "v": 1,
            "channel": "whatsapp",
            "direction": "out",
            "to": raw_inbound.get("from"),
            "chat_id": raw_inbound.get("chat_id"),
            "correlation_id": envelope.correlation_id,
            "type": "text",
            "text": envelope.text or "",
            "meta": envelope.metadata or {},
        }

        await self.room.local_participant.publish_data(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            topic="whatsapp.out",
            reliable=True,
        )
        logger.info("WhatsAppEgressAdapter published whatsapp.out: %s", payload)
