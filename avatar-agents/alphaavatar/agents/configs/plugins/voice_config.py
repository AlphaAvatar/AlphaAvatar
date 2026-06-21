# Copyright 2025 AlphaAvatar project
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
import importlib
import importlib.util
from typing import Literal

from livekit.agents import stt, tts, vad
from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin

# livekit turn_detector
english_spec = importlib.util.find_spec("livekit.plugins.turn_detector.english")
multilingual_spec = importlib.util.find_spec("livekit.plugins.turn_detector.multilingual")

if english_spec is not None:
    importlib.import_module("livekit.plugins.turn_detector.english")

if multilingual_spec is not None:
    importlib.import_module("livekit.plugins.turn_detector.multilingual")


# alphaavatar voice plugins
importlib.import_module("alphaavatar.plugins.voice")


class STTConfig(BaseModel):
    """Configuration for the STT plugin used in the agent."""

    model_config = ConfigDict(extra="forbid")

    plugin: Literal["openai"] | None = Field(
        default=None,
        description="STT plugin to use for speech-to-text.",
    )
    model: str | None = Field(
        default=None,
        description="Model to use for speech-to-text.",
    )

    def get_plugin(self) -> stt.STT | None:
        if self.model is None:
            return None

        match self.plugin:
            case "openai":
                try:
                    from livekit.plugins import openai
                except ImportError as e:
                    raise ImportError(
                        "The 'openai.STT' plugin is required for livekit.plugins.openai "
                        "but is not installed.\n"
                        "Install it with: `pip install livekit-plugins-openai`"
                    ) from e

                return openai.STT(model=self.model)

            case _:
                return None


class TTSConfig(BaseModel):
    """Configuration for the TTS plugin used in the agent."""

    model_config = ConfigDict(extra="forbid")

    plugin: Literal["openai", "voiceai"] | None = Field(
        default=None,
        description="TTS plugin to use for text-to-speech.",
    )
    model: str | None = Field(
        default=None,
        description="Model to use for text-to-speech.",
    )
    speaker: str | None = Field(
        default=None,
        description="Speaker to use for text-to-speech. For voice.ai, this corresponds to voice_id.",
    )
    instructions: str | None = Field(
        default=None,
        description="Instructions for the TTS model.",
    )

    def get_plugin(self) -> tts.TTS | None:
        if self.plugin is None:
            return None

        match self.plugin:
            case "openai":
                try:
                    from livekit.plugins import openai
                except ImportError as e:
                    raise ImportError(
                        "The 'openai.TTS' plugin is required for livekit.plugins.openai "
                        "but is not installed.\n"
                        "Install it with: `pip install livekit-plugins-openai`"
                    ) from e

                if self.model is None:
                    raise ValueError("voice.tts.model is required when voice.tts.plugin='openai'")

                if self.speaker is None:
                    raise ValueError("voice.tts.speaker is required when voice.tts.plugin='openai'")

                return openai.TTS(
                    model=self.model,
                    voice=self.speaker,
                    instructions=self.instructions,
                )

            case _:
                return AvatarPlugin.get_avatar_plugin(
                    AvatarModule.VOICE_TTS,
                    self.plugin,
                    model=self.model,
                    speaker=self.speaker,
                    instructions=self.instructions,
                )


class VADConfig(BaseModel):
    """Configuration for the VAD plugin used in the agent."""

    model_config = ConfigDict(extra="forbid")

    plugin: Literal["silero"] | None = Field(
        default=None,
        description="VAD plugin to use for voice activity detection.",
    )

    def get_plugin(self) -> vad.VAD | None:
        match self.plugin:
            case "silero":
                try:
                    from livekit.plugins import silero
                except ImportError as e:
                    raise ImportError(
                        "The 'silero.VAD' plugin is required for livekit.plugins.silero "
                        "but is not installed.\n"
                        "Install it with: `pip install livekit-plugins-silero`"
                    ) from e

                return silero.VAD.load()

            case _:
                return None


class TurnDetectionConfig(BaseModel):
    """Configuration for turn detection."""

    model_config = ConfigDict(extra="forbid")

    plugin: Literal["multilingual", "english"] | None = Field(
        default=None,
        description="Turn detection plugin to use for detecting speech turns.",
    )

    def get_plugin(self):
        match self.plugin:
            case "multilingual":
                try:
                    from livekit.plugins.turn_detector.multilingual import MultilingualModel
                except ImportError as e:
                    raise ImportError(
                        "The 'turn_detector.multilingual' plugin is required "
                        "but is not installed.\n"
                        "Install it with: `pip install livekit-plugins-turn-detector`"
                    ) from e

                return MultilingualModel()

            case "english":
                try:
                    from livekit.plugins.turn_detector.english import EnglishModel
                except ImportError as e:
                    raise ImportError(
                        "The 'turn_detector.english' plugin is required "
                        "but is not installed.\n"
                        "Install it with: `pip install livekit-plugins-turn-detector`"
                    ) from e

                return EnglishModel()

            case _:
                return None


class VoiceConfig(BaseModel):
    """Configuration for LiveKit voice plugins used in the agent."""

    model_config = ConfigDict(extra="forbid")

    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    turn_detection: TurnDetectionConfig = Field(default_factory=TurnDetectionConfig)

    allow_interruptions: bool = Field(
        default=True,
        description="Allow interruptions during speech.",
    )

    def get_stt_plugin(self):
        return self.stt.get_plugin()

    def get_tts_plugin(self):
        return self.tts.get_plugin()

    def get_vad_plugin(self):
        return self.vad.get_plugin()

    def get_turn_detection_plugin(self):
        return self.turn_detection.get_plugin()
