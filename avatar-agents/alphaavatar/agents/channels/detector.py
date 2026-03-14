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

from livekit import rtc

from .schema.room_type import RoomType


def _safe_json_loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def detect_room_type(room: rtc.Room) -> RoomType:
    # 1) Prioritize room metadata
    room_meta = _safe_json_loads(getattr(room, "metadata", None))
    room_type = room_meta.get("room_type") or room_meta.get("channel")

    if room_type == RoomType.WHATSAPP.value:
        return RoomType.WHATSAPP
    if room_type == RoomType.TELEGRAM.value:
        return RoomType.TELEGRAM
    if room_type == RoomType.SLACK.value:
        return RoomType.SLACK
    if room_type == RoomType.DISCORD.value:
        return RoomType.DISCORD
    if room_type == RoomType.API.value:
        return RoomType.API
    if room_type == RoomType.WEB_APP.value:
        return RoomType.WEB_APP

    # 2) Fallback: Determine based on room name prefix
    room_name = getattr(room, "name", "") or ""

    if room_name.startswith("wa_"):
        return RoomType.WHATSAPP
    if room_name.startswith("tg_"):
        return RoomType.TELEGRAM
    if room_name.startswith("slack_"):
        return RoomType.SLACK
    if room_name.startswith("discord_"):
        return RoomType.DISCORD
    if room_name.startswith("api_"):
        return RoomType.API

    # 3) The default is WEB_APP
    return RoomType.WEB_APP
