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

from typing import TYPE_CHECKING

from alphaavatar.agents.runtime.plugin import AvatarModulePlugin

from ..log import logger
from ..version import __version__

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.voice import TTSBase


class OpenAITTSPlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)

    def get_plugin(
        self,
        *,
        model: str,
        speaker: str | None = None,
        instructions: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        frame_size_ms: int = 20,
        queue_frames: int = 8,
        max_streams: int = 4,
        max_audio_seconds: float = 120.0,
    ) -> TTSBase:
        from .openai import OpenAITTS
        from .pcm import PCMSettings

        if speaker is None:
            raise ValueError("OpenAI TTS requires voice.tts.speaker")

        return OpenAITTS(
            model=model,
            speaker=speaker,
            instructions=instructions,
            base_url=base_url,
            settings=PCMSettings(
                timeout, frame_size_ms, queue_frames, max_streams, max_audio_seconds
            ),
        )


class VoiceAITTSPlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)

    def get_plugin(
        self,
        *,
        model: str,
        speaker: str | None = None,
        instructions: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        frame_size_ms: int = 20,
        queue_frames: int = 8,
        max_streams: int = 4,
        max_audio_seconds: float = 120.0,
    ) -> TTSBase:
        from .pcm import PCMSettings
        from .voiceai import VoiceAITTS

        if instructions is not None:
            raise ValueError("Voice.ai TTS does not support voice.tts.instructions")

        return VoiceAITTS(
            model=model,
            speaker=speaker,
            base_url=base_url,
            settings=PCMSettings(
                timeout, frame_size_ms, queue_frames, max_streams, max_audio_seconds
            ),
        )
