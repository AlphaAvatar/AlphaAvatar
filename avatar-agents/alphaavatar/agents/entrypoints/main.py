import json
import logging
import textwrap
from functools import partial
from dotenv import load_dotenv
from typing import Any, Optional

from livekit import agents
from livekit.agents import AgentSession, RoomInputOptions
from livekit.agents.job import AutoSubscribe
from livekit.plugins import noise_cancellation

from alphaavatar.agents.avatar import AvatarEngine
from alphaavatar.agents.configs import read_args, get_avatar_args, AvatarConfig


load_dotenv()

logger = logging.getLogger("alphaavatar.agent")


def init_warm():
    try:
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
    except:
        pass


init_warm()


async def entrypoint(
    avatar_config: AvatarConfig,
    ctx: agents.JobContext
):
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
    chat_id: {chat_id}
    avatar_config: {avatar_config}"""))

    # Build Session & Avatar
    session = AgentSession()
    avatar_engine = AvatarEngine(avatar_config)

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
    avatar_config = get_avatar_args(args)
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=partial(entrypoint, avatar_config)))


if __name__ == "__main__":
    main()
