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
import json
import textwrap
from functools import partial

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentSession, RoomInputOptions
from livekit.agents.job import AutoSubscribe
from livekit.plugins import noise_cancellation

from alphaavatar.agents.avatar import AvatarEngine
from alphaavatar.agents.configs import AvatarConfig, SessionConfig, get_avatar_args, read_args
from alphaavatar.agents.log import logger
from alphaavatar.agents.utils import get_session_id, get_user_id

load_dotenv()


async def entrypoint(avatar_config: AvatarConfig, ctx: agents.JobContext):
    # Wait connecting...
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Get Metadata
    participant = await ctx.wait_for_participant()
    participant_metadata = json.loads(participant.metadata) if participant.metadata else {}
    user_id = participant_metadata.get("user_id", get_user_id())
    session_id = participant_metadata.get("session_id", get_session_id())
    session_config = SessionConfig(
        user_id=user_id,
        session_id=session_id,
    )

    logger.info(
        textwrap.dedent(f"""Connecting to room...
    - Room Name: {ctx.room.name}
    - Token: {ctx._info.token}
    - Session Config: {session_config}
    - Avatar Config: {avatar_config}""")
    )

    # Build Session & Avatar
    session = AgentSession()
    avatar_engine = AvatarEngine(session_config=session_config, avatar_config=avatar_config)
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


def main() -> None:
    args = read_args()
    avatar_config = get_avatar_args(args)
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=partial(entrypoint, avatar_config)))


if __name__ == "__main__":
    main()
