from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from livekit.agents import llm, stt, tokenize, tts, vad
from livekit.agents.voice.agent_session import TurnDetectionMode


@dataclass
class LiveKitPluginArguments:
    """Configuration for LiveKit plugins used in the agent."""

    stt_plugin: Optional[stt.STT] = field(
        default=None,
        metadata={"help": "STT plugin to use for speech-to-text."},
    )
    tts_plugin: Optional[tts.TTS] = field(
        default=None,
        metadata={"help": "TTS plugin to use for text-to-speech."},
    )
    llm_plugin: Optional[llm.LLM] = field(
        default=None,
        metadata={"help": "LLM plugin to use for language/real-time model interactions."},
    )
    vad_plugin: Optional[vad.VAD] = field(
        default=None,
        metadata={"help": "VAD plugin to use for voice activity detection."},
    )
    turn_detection_plugin: Optional[TurnDetectionMode] = field(
        default=None,
        metadata={"help": "Turn detection plugin to use for detecting speech turns."},
    )
    allow_interruptions: bool = field(
        default=True,
        metadata={"help": "Allow interruptions during speech."},
    )
    
    def __post_init__(self):
        pass
    
    def to_dict(self) -> dict[str, Any]:
        args = asdict(self)
        args = {k: f"<{k.upper()}>" if k.endswith("token") else v for k, v in args.items()}
        return args
