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
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

from .schemas import WAInboundEvent, WAOutboundEvent

logger = logging.getLogger("aa.whatsapp.core")
logging.basicConfig(level=logging.INFO)

# Save the driver for the current connection (only one instance is supported initially)
DRIVER_CONNS: set[WebSocketServerProtocol] = set()

# Simple deduplication (MVP: in-process set; to be replaced with sqlite/redis later)
SEEN_MESSAGE_IDS: set[str] = set()


async def handle_driver(ws: WebSocketServerProtocol):
    DRIVER_CONNS.add(ws)
    logger.info("Driver connected: %s", ws.remote_address)
    try:
        async for msg in ws:
            data = json.loads(msg)
            if data.get("direction") == "in":
                inbound = WAInboundEvent.model_validate(data)
                if inbound.message_id in SEEN_MESSAGE_IDS:
                    logger.info("Duplicate message_id ignored: %s", inbound.message_id)
                    continue
                SEEN_MESSAGE_IDS.add(inbound.message_id)

                # First, perform an echo test: return inbound.text to the driver as is.
                out = WAOutboundEvent(
                    to=inbound.from_,
                    chat_id=inbound.chat_id,
                    correlation_id=inbound.message_id,
                    text=f"[echo] {inbound.text}",
                    meta={"echo": True},
                )
                await broadcast_to_driver(out.model_dump())
            else:
                logger.warning("Unknown message: %s", data)
    except websockets.ConnectionClosed:
        logger.info("Driver disconnected")
    finally:
        DRIVER_CONNS.discard(ws)


async def broadcast_to_driver(payload: dict[str, Any]):
    if not DRIVER_CONNS:
        logger.warning("No driver connected; dropping outbound payload")
        return
    msg = json.dumps(payload, ensure_ascii=False)
    await asyncio.gather(*(ws.send(msg) for ws in list(DRIVER_CONNS)))


async def ws_main(host: str = "127.0.0.1", port: int = 18789):
    async with websockets.serve(handle_driver, host, port, ping_interval=20, ping_timeout=20):
        logger.info("WhatsApp Core WS listening on ws://%s:%d", host, port)
        await asyncio.Future()  # run forever


def main():
    asyncio.run(ws_main())
