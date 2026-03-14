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
from enum import Enum

from .room_type import RoomType


class SessionType(str, Enum):
    CHAT = "chat"
    TOOL = "agent"
    VIDEO = "video"
    AUDIO = "audio"


def resolve_session_type(room_type: RoomType, participant_metadata: dict) -> SessionType:
    raw = participant_metadata.get("session_type")
    if raw:
        try:
            return SessionType(raw)
        except ValueError:
            pass

    if room_type == RoomType.WHATSAPP:
        return SessionType.CHAT

    if room_type == RoomType.WEB_APP:
        return SessionType.AUDIO

    raise ValueError(f"Unable to resolve session type for room type: {room_type}")
