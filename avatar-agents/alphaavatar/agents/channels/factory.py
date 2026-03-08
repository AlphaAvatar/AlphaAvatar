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

from dataclasses import dataclass
from typing import Any

from livekit import rtc
from livekit.agents import AgentSession

from alphaavatar.agents.log import logger

from .detector import detect_room_type
from .registry import get_channel_adapters_builder
from .room_type import RoomType


@dataclass
class BuiltChannelAdapters:
    room_type: RoomType
    ingress: Any | None = None
    egress: Any | None = None


def build_channel_adapters(
    *,
    room: rtc.Room,
    session: AgentSession,
    on_input=None,
    **kwargs,
) -> BuiltChannelAdapters:
    room_type = detect_room_type(room)
    logger.info("Detected room_type=%s room=%s", room_type, room.name)

    builder = get_channel_adapters_builder(room_type)
    if builder is None:
        return BuiltChannelAdapters(room_type=room_type)

    ingress = (
        builder.build_ingress(room=room, session=session, on_input=on_input, **kwargs)
        if builder.build_ingress
        else None
    )
    egress = (
        builder.build_egress(room=room, session=session, **kwargs) if builder.build_egress else None
    )

    return BuiltChannelAdapters(
        room_type=room_type,
        ingress=ingress,
        egress=egress,
    )
