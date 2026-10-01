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

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class SessionType(str, Enum):
    CHAT = "chat"
    TOOL = "agent"
    AUDIO = "audio"
    VIDEO = "video"


@dataclass(frozen=True)
class SessionMode:
    text_input_enabled: bool = True
    audio_input_enabled: bool = True
    video_input_enabled: bool = False
    audio_output_enabled: bool = True
    text_output_enabled: bool = True
    enable_noise_cancellation: bool = True


def resolve_session_type(participant_metadata: Mapping[str, object]) -> SessionType:
    raw = participant_metadata.get("session_type")
    if raw is None:
        return SessionType.VIDEO
    if not isinstance(raw, str):
        raise ValueError("session_type must be a string: chat, agent, audio, or video")
    try:
        return SessionType(raw)
    except ValueError as exc:
        raise ValueError(f"Unsupported session_type: {raw!r}") from exc


def resolve_session_mode(session_type: SessionType) -> SessionMode:
    if session_type in (SessionType.CHAT, SessionType.TOOL):
        return SessionMode(
            audio_input_enabled=False,
            audio_output_enabled=False,
            enable_noise_cancellation=False,
        )
    if session_type == SessionType.AUDIO:
        return SessionMode()
    if session_type == SessionType.VIDEO:
        return SessionMode(video_input_enabled=True)
    raise ValueError(f"Unsupported session_type: {session_type!r}")
