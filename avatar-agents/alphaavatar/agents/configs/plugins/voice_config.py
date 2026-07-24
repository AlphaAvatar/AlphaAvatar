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

from livekit.agents import tts, vad as livekit_vad
from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.avatar.voice import STTBase, VADBase
from alphaavatar.agents.runtime.inference import InferenceExecutor

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
    """Configuration for AlphaAvatar speech-to-text."""

    model_config = ConfigDict(extra="forbid")

    plugin: Literal["openai_realtime", "openai_segment"] | None = Field(
        default=None,
        description="STT provider implementation used by Interaction Router.",
    )
    model: str | None = Field(
        default=None,
        description="Model used by the AlphaAvatar STT provider.",
    )
    delay: Literal["minimal", "low", "medium", "high", "xhigh"] = Field(
        default="low",
        description="Realtime transcription latency/quality preference.",
    )
    base_url: str | None = Field(
        default=None,
        description="Optional provider API base URL.",
    )

    def get_plugin(self) -> STTBase | None:
        if self.model is None:
            raise ValueError(f"voice.stt.model is required when voice.stt.plugin={self.plugin!r}")

        kwargs = {
            "model": self.model,
        }

        if self.plugin == "openai_realtime":
            kwargs["delay"] = self.delay

        if self.base_url is not None:
            kwargs["base_url"] = self.base_url

        return AvatarPlugin.get_avatar_plugin(
            AvatarModule.VOICE_STT,
            self.plugin,
            **kwargs,
        )


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
    """Configuration for AlphaAvatar voice activity detection."""

    model_config = ConfigDict(extra="forbid")

    plugin: Literal["silero"] | None = Field(
        default=None,
        description="VAD plugin used by Interaction Router.",
    )
    min_speech_duration: float = Field(default=0.05, ge=0.0)
    min_silence_duration: float = Field(default=0.55, ge=0.0)
    activation_threshold: float = Field(default=0.5, gt=0.0, le=1.0)
    deactivation_threshold: float | None = Field(default=None, gt=0.0, le=1.0)
    smoothing_alpha: float = Field(default=0.35, ge=0.0, lt=1.0)
    queue_size: int = Field(default=256, gt=0)
    inference_timeout_sec: float = Field(default=0.5, gt=0.0)

    def get_plugin(
        self,
        *,
        inference_executor: InferenceExecutor,
    ) -> VADBase | None:
        return AvatarPlugin.get_avatar_plugin(
            AvatarModule.VOICE_VAD,
            self.plugin,
            min_speech_duration=self.min_speech_duration,
            min_silence_duration=self.min_silence_duration,
            activation_threshold=self.activation_threshold,
            deactivation_threshold=self.deactivation_threshold,
            smoothing_alpha=self.smoothing_alpha,
            queue_size=self.queue_size,
            inference_timeout_sec=self.inference_timeout_sec,
            inference_executor=inference_executor,
        )

    def get_legacy_livekit_plugin(self) -> livekit_vad.VAD:
        """
        Temporary compatibility VAD for the existing LiveKit Agent voice path.

        Remove after STT and Persona Speaker consume Router output.
        """
        try:
            from livekit.plugins import silero
        except ImportError as error:
            raise ImportError(
                "The temporary livekit-plugins-silero dependency is required "
                "until the legacy speaker_node path is removed."
            ) from error

        deactivation_threshold = (
            self.deactivation_threshold
            if self.deactivation_threshold is not None
            else max(self.activation_threshold - 0.15, 0.01)
        )

        return silero.VAD.load(
            min_speech_duration=self.min_speech_duration,
            min_silence_duration=self.min_silence_duration,
            activation_threshold=self.activation_threshold,
            deactivation_threshold=deactivation_threshold,
            sample_rate=16_000,
        )


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
    """Configuration for AlphaAvatar voice plugins used in the agent."""

    model_config = ConfigDict(extra="forbid")

    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    turn_detection: TurnDetectionConfig = Field(default_factory=TurnDetectionConfig)

    allow_interruptions: bool = Field(
        default=True,
        description="Allow interruptions during speech.",
    )

    def get_stt_plugin(self) -> STTBase | None:
        return self.stt.get_plugin()

    def get_tts_plugin(self):
        return self.tts.get_plugin()

    def get_vad_plugin(
        self,
        *,
        inference_executor: InferenceExecutor,
    ) -> VADBase | None:
        return self.vad.get_plugin(
            inference_executor=inference_executor,
        )

    def get_legacy_livekit_vad_plugin(self) -> livekit_vad.VAD | None:
        return self.vad.get_legacy_livekit_plugin()

    def get_turn_detection_plugin(self):
        return self.turn_detection.get_plugin()
