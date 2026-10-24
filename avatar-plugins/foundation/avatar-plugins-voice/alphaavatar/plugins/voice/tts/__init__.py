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
        speed: float = 1.0,
        base_url: str | None = None,
        timeout: float = 30.0,
        first_audio_timeout: float = 5.0,
        read_timeout: float = 15.0,
        slow_response_after: float = 2.5,
        trust_env: bool = False,
        first_audio_hedge_after: float | None = 2.5,
        max_retries: int = 1,
        retry_interval: float = 0.1,
        frame_size_ms: int = 20,
        queue_frames: int = 64,
        max_streams: int = 4,
        max_audio_seconds: float = 120.0,
    ) -> TTSBase:
        from .codec.pcm import PCMSettings
        from .openai import OpenAITTS

        if speaker is None:
            raise ValueError("OpenAI TTS requires voice.tts.speaker")

        return OpenAITTS(
            model=model,
            speaker=speaker,
            instructions=instructions,
            speed=speed,
            base_url=base_url,
            settings=PCMSettings(
                timeout=timeout,
                first_audio_timeout=first_audio_timeout,
                read_timeout=read_timeout,
                slow_response_after=slow_response_after,
                trust_env=trust_env,
                first_audio_hedge_after=first_audio_hedge_after,
                max_retries=max_retries,
                retry_interval=retry_interval,
                frame_size_ms=frame_size_ms,
                queue_frames=queue_frames,
                max_streams=max_streams,
                max_audio_seconds=max_audio_seconds,
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
        speed: float = 1.0,
        base_url: str | None = None,
        timeout: float = 30.0,
        first_audio_timeout: float = 5.0,
        read_timeout: float = 15.0,
        slow_response_after: float = 2.5,
        trust_env: bool = False,
        first_audio_hedge_after: float | None = 2.5,
        max_retries: int = 1,
        retry_interval: float = 0.1,
        frame_size_ms: int = 20,
        queue_frames: int = 64,
        max_streams: int = 4,
        max_audio_seconds: float = 120.0,
    ) -> TTSBase:
        from .codec.pcm import PCMSettings
        from .voiceai import VoiceAITTS

        if instructions is not None:
            raise ValueError("Voice.ai TTS does not support voice.tts.instructions")

        return VoiceAITTS(
            model=model,
            speaker=speaker,
            speed=speed,
            base_url=base_url,
            settings=PCMSettings(
                timeout=timeout,
                first_audio_timeout=first_audio_timeout,
                read_timeout=read_timeout,
                slow_response_after=slow_response_after,
                trust_env=trust_env,
                first_audio_hedge_after=first_audio_hedge_after,
                max_retries=max_retries,
                retry_interval=retry_interval,
                frame_size_ms=frame_size_ms,
                queue_frames=queue_frames,
                max_streams=max_streams,
                max_audio_seconds=max_audio_seconds,
            ),
        )
