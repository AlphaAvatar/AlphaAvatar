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
import importlib.util
from typing import Literal

from livekit.agents import llm, stt, tts, vad
from pydantic import BaseModel, Field

english_spec = importlib.util.find_spec("livekit.plugins.turn_detector.english")
multilingual_spec = importlib.util.find_spec("livekit.plugins.turn_detector.multilingual")
if english_spec is not None:
    importlib.import_module("livekit.plugins.turn_detector.english")
if multilingual_spec is not None:
    importlib.import_module("livekit.plugins.turn_detector.multilingual")


class STTArguments(BaseModel):
    """Configuration for the STT plugin used in the agent."""

    stt_plugin: Literal["openai"] | None = Field(
        default=None,
        description="STT plugin to use for speech-to-text.",
    )
    stt_model: str | None = Field(
        default=None,
        description="Model to use for speech-to-text.",
    )

    def get_stt_plugin(self) -> stt.STT | None:
        """Returns the STT plugin base on stt config."""
        if self.stt_model is None:
            return None

        match self.stt_plugin:
            case "openai":
                try:
                    from livekit.plugins import openai
                except ImportError:
                    raise ImportError(
                        "The 'openai.STT' plugin is required for livekit.plugins.openai but is not installed.\n"
                        "To fix this, install the optional dependency: `pip install livekit-plugins-openai`"
                    )
                return openai.STT(model=self.stt_model)
            case _:
                return None


class TTSArguments(BaseModel):
    """Configuration for the TTS plugin used in the agent."""

    tts_plugin: Literal["openai"] | None = Field(
        default=None,
        description="TTS plugin to use for text-to-speech.",
    )
    tts_model: str | None = Field(
        default=None,
        description="Model to use for text-to-speech.",
    )
    tts_voice: str | None = Field(
        default=None,
        description="Voice to use for text-to-speech.",
    )
    tts_instructions: str | None = Field(
        default=None,
        description="Instructions for the TTS model.",
    )

    def get_tts_plugin(self) -> tts.TTS | None:
        """Returns the TTS plugin based on tts config."""
        match self.tts_plugin:
            case "openai":
                try:
                    from livekit.plugins import openai
                except ImportError:
                    raise ImportError(
                        "The 'openai.TTS' plugin is required for livekit.plugins.openai but is not installed.\n"
                        "To fix this, install the optional dependency: `pip install livekit-plugins-openai`"
                    )

                assert self.tts_model is not None
                assert self.tts_voice is not None
                return openai.TTS(
                    model=self.tts_model,
                    voice=self.tts_voice,
                    instructions=self.tts_instructions,
                )
            case _:
                return None


class LLMArguments(BaseModel):
    """Configuration for the LLM plugin used in the agent."""

    llm_plugin: Literal["openai"] | None = Field(
        default=None,
        description="LLM plugin to use for language/real-time model interactions.",
    )
    llm_model: str | None = Field(
        default=None,
        description="Model to use for language/real-time model interactions.",
    )

    def get_llm_plugin(self) -> llm.LLM | llm.RealtimeModel | None:
        """Returns the LLM plugin based on llm config."""

        if self.llm_model is None:
            return None

        match self.llm_plugin:
            case "openai":
                try:
                    from livekit.plugins import openai
                except ImportError:
                    raise ImportError(
                        "The 'openai.LLM' plugin is required for livekit.plugins.openai but is not installed.\n"
                        "To fix this, install the optional dependency: `pip install livekit-plugins-openai`"
                    )
                return openai.LLM(model=self.llm_model)
            case _:
                return None


class VADArguments(BaseModel):
    """Configuration for the VAD plugin used in the agent."""

    vad_plugin: Literal["silero"] | None = Field(
        default=None,
        description="VAD plugin to use for voice activity detection.",
    )

    def get_vad_plugin(self) -> vad.VAD | None:
        """Returns the VAD plugin based on vad config."""
        match self.vad_plugin:
            case "silero":
                try:
                    from livekit.plugins import silero
                except ImportError:
                    raise ImportError(
                        "The 'silero.VAD' plugin is required for livekit.plugins.silero but is not installed.\n"
                        "To fix this, install the optional dependency: `pip install livekit-plugins-silero`"
                    )
                return silero.VAD.load()
            case _:
                return None


class LiveKitPluginConfig(STTArguments, TTSArguments, LLMArguments, VADArguments):
    """Configuration for LiveKit plugins used in the agent."""

    turn_detection_plugin: Literal["multilingual", "english"] | None = Field(
        default=None,
        description="Turn detection plugin to use for detecting speech turns.",
    )
    allow_interruptions: bool = Field(
        default=True,
        description="Allow interruptions during speech.",
    )

    def get_turn_detection_plugin(self):
        """Returns the turn detection plugin based on the configuration."""
        match self.turn_detection_plugin:
            case "multilingual":
                try:
                    from livekit.plugins.turn_detector.multilingual import MultilingualModel
                except ImportError:
                    raise ImportError(
                        "The 'turn_detector.multilingual' plugin is required for livekit.plugins.turn_detector but is not installed.\n"
                        "To fix this, install the optional dependency: `pip install livekit-plugins-turn-detector`"
                    )
                return MultilingualModel()
            case "english":
                try:
                    from livekit.plugins.turn_detector.english import EnglishModel
                except ImportError:
                    raise ImportError(
                        "The 'turn_detector.english' plugin is required for livekit.plugins.turn_detector but is not installed.\n"
                        "To fix this, install the optional dependency: `pip install livekit-plugins-turn-detector`"
                    )
                return EnglishModel()
            case _:
                return None
