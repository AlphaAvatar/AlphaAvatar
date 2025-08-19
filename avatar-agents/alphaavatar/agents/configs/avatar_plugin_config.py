from typing import Any, Optional, Literal
from pydantic.dataclasses import dataclass
from pydantic import Field, ConfigDict

from livekit.agents import stt, tts, llm, vad


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class STTArguments:
    """Configuration for the STT plugin used in the agent."""

    stt_plugin: Literal["openai"] = Field(
        default=None,
        description="STT plugin to use for speech-to-text.",
    )
    stt_model: str = Field(
        default=None,
        description="Model to use for speech-to-text.",
    )

    def get_stt_plugin(self) -> stt.STT:
        """Returns the STT plugin base on stt config."""
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


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class TTSArguments:
    """Configuration for the TTS plugin used in the agent."""

    tts_plugin: Literal["openai"] = Field(
        default=None,
        description="TTS plugin to use for text-to-speech.",
    )
    tts_model: str = Field(
        default=None,
        description="Model to use for text-to-speech.",
    )
    tts_voice: str = Field(
        default=None,
        description="Voice to use for text-to-speech.",
    )
    tts_instructions: str = Field(
        default=None,
        description="Instructions for the TTS model.",
    )

    def get_tts_plugin(self) -> tts.TTS:
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
                return openai.TTS(
                    model=self.tts_model,
                    voice=self.tts_voice,
                    instructions=self.tts_instructions,
                )
            case _:
                return None


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class LLMArguments:
    """Configuration for the LLM plugin used in the agent."""

    llm_plugin: Literal["openai"] = Field(
        default=None,
        description="LLM plugin to use for language/real-time model interactions.",
    )
    llm_model: str = Field(
        default=None,
        description="Model to use for language/real-time model interactions.",
    )

    def get_llm_plugin(self) -> Optional[llm.LLM | llm.RealtimeModel]:
        """Returns the LLM plugin based on llm config."""
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


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class VADArguments:
    """Configuration for the VAD plugin used in the agent."""

    vad_plugin: Literal["silero"] = Field(
        default=None,
        description="VAD plugin to use for voice activity detection.",
    )

    def get_vad_plugin(self) -> vad.VAD:
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


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class LiveKitPluginConfig(STTArguments, TTSArguments, LLMArguments, VADArguments):
    """Configuration for LiveKit plugins used in the agent."""

    turn_detection_plugin: Literal["multilingual", "english"] = Field(
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

    def to_dict(self) -> dict[str, Any]:
        # Pydantic dataclass 会有 .__pydantic_model__.model_dump()
        data = self.__pydantic_model__.model_dump(self)
        return {
            k: (f"<{k.upper()}>" if isinstance(v, str) and k.endswith("token") else v)
            for k, v in data.items()
        }
