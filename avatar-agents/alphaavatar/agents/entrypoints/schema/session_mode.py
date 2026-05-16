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
from dataclasses import dataclass

from .session_type import SessionType


@dataclass(frozen=True)
class SessionMode:
    text_input_enabled: bool = True
    audio_input_enabled: bool = True
    video_input_enabled: bool = False

    audio_output_enabled: bool = True
    text_output_enabled: bool = True

    # Internal RoomOptions/audio pipeline setting.
    # Do not expose this to InteractionMethod or runtime prompt.
    enable_noise_cancellation: bool = True


def resolve_session_mode(session_type: SessionType) -> SessionMode:
    if session_type == SessionType.CHAT:
        return SessionMode(
            text_input_enabled=True,
            audio_input_enabled=False,
            video_input_enabled=False,
            audio_output_enabled=False,
            text_output_enabled=True,
            enable_noise_cancellation=False,
        )

    if session_type == SessionType.TOOL:
        return SessionMode(
            text_input_enabled=True,
            audio_input_enabled=False,
            video_input_enabled=False,
            audio_output_enabled=False,
            text_output_enabled=True,
            enable_noise_cancellation=False,
        )

    if session_type == SessionType.AUDIO:
        return SessionMode(
            text_input_enabled=True,
            audio_input_enabled=True,
            video_input_enabled=False,
            audio_output_enabled=True,
            text_output_enabled=True,
            enable_noise_cancellation=True,
        )

    if session_type == SessionType.VIDEO:
        return SessionMode(
            text_input_enabled=True,
            audio_input_enabled=True,
            video_input_enabled=True,
            audio_output_enabled=True,
            text_output_enabled=True,
            enable_noise_cancellation=True,
        )

    return SessionMode()
