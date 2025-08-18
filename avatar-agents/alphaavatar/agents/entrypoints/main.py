import json
import logging
import textwrap
from dotenv import load_dotenv
from typing import Any, Optional

from livekit import agents
from livekit.agents import AgentSession, RoomInputOptions
from livekit.agents.job import AutoSubscribe, JobProcess
from livekit.plugins import (
    openai,
    noise_cancellation,
    silero,
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from alphaavatar.agents.configs import read_args
from alphaavatar.agents.avatar import AvatarEngine

load_dotenv()

logger = logging.getLogger("alphaavatar.agent")


async def entrypoint(ctx: agents.JobContext):
    # Wait connecting...
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Get Metadata
    participant = await ctx.wait_for_participant()
    participant_metadata = (
        json.loads(participant.metadata) if participant.metadata else {}
    )
    user_id = participant_metadata.get("user_id", None)
    chat_id = participant_metadata.get("chat_id", None)

    logger.info(textwrap.dedent(f"""Connecting to room... 
room name: {ctx.room.name}
token: {ctx._info.token}
user_id: {user_id}
chat_id: {chat_id}"""))

    # Build Session & Avatar
    session = AgentSession()
    avatar_engine = AvatarEngine(
        # Internal
        instructions="You are a helpful voice AI assistant.",
        # External
        turn_detection=MultilingualModel(),
        vad=silero.VAD.load(),
        stt=openai.STT(model="gpt-4o-transcribe"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(
            model="gpt-4o-mini-tts",
            voice="ash",
            instructions="Speak in a friendly and conversational tone.",
        ),
        allow_interruptions=True,
    )

    await session.start(
        room=ctx.room,
        agent=avatar_engine,
        room_input_options=RoomInputOptions(
            # LiveKit Cloud enhanced noise cancellation
            # - If self-hosting, omit this parameter
            # - For telephony applications, use `BVCTelephony` for best results
            noise_cancellation=noise_cancellation.BVC(), 
        ),
    )

    await session.generate_reply(
        instructions="Greet the user and offer your assistance."
    )


def main(args: Optional[dict[str, Any]] = None) -> None:
    args = read_args(args)

    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))


if __name__ == "__main__":
    main()
