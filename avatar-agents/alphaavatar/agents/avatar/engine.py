"""Avatar Launch Engine"""
from livekit.agents import Agent, llm, stt, tts, vad
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.voice.agent_session import TurnDetectionMode
from livekit.agents.llm import mcp

from alphaavatar.agents.memory import Memory


class AvatarEngine(Agent):
    def __init__(
        self,
        *,
        # Internal
        instructions: str,
        memory: NotGivenOr[Memory | None] = NOT_GIVEN,
        # External
        chat_ctx: NotGivenOr[llm.ChatContext | None] = NOT_GIVEN,
        tools: list[llm.FunctionTool | llm.RawFunctionTool] | None = None,
        turn_detection: NotGivenOr[TurnDetectionMode | None] = NOT_GIVEN,
        stt: NotGivenOr[stt.STT | None] = NOT_GIVEN,
        vad: NotGivenOr[vad.VAD | None] = NOT_GIVEN,
        llm: NotGivenOr[llm.LLM | llm.RealtimeModel | None] = NOT_GIVEN,
        tts: NotGivenOr[tts.TTS | None] = NOT_GIVEN,
        mcp_servers: NotGivenOr[list[mcp.MCPServer] | None] = NOT_GIVEN,
        allow_interruptions: NotGivenOr[bool] = NOT_GIVEN,
        min_consecutive_speech_delay: NotGivenOr[float] = NOT_GIVEN,
        use_tts_aligned_transcript: NotGivenOr[bool] = NOT_GIVEN,
        # 
    ) -> None:
        super().__init__(
            instructions=instructions,
            chat_ctx=chat_ctx,
            tools=tools,
            turn_detection=turn_detection,
            stt=stt,
            vad=vad,
            llm=llm,
            tts=tts,
            mcp_servers=mcp_servers,
            allow_interruptions=allow_interruptions,
            min_consecutive_speech_delay=min_consecutive_speech_delay,
            use_tts_aligned_transcript=use_tts_aligned_transcript
        )
        self._memory = memory
