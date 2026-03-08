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
from alphaavatar.agents.channels.bootstrap import register_builtin_channels
from alphaavatar.agents.channels.factory import build_channel_adapters
from alphaavatar.agents.channels.room_type import SUPPORTED_ADAPTER_TYPES
from alphaavatar.agents.configs import AvatarConfig, SessionConfig, get_avatar_args, read_args
from alphaavatar.agents.io.dispatcher import InputDispatcher
from alphaavatar.agents.log import logger
from alphaavatar.agents.utils import SessionType, get_session_id, get_user_id

load_dotenv()


def worker_load(worker) -> float:
    return min(len(worker.active_jobs) / 10.0, 1.0)


async def entrypoint(avatar_config: AvatarConfig, ctx: agents.JobContext):
    # Wait connecting...
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Get Metadata
    agent_identity = ctx.token_claims().identity
    participant = await ctx.wait_for_participant()
    participant_metadata = json.loads(participant.metadata) if participant.metadata else {}
    user_id = participant_metadata.get("user_id", get_user_id())
    session_id = participant_metadata.get("session_id", get_session_id(SessionType.CHAT))
    session_config = SessionConfig(
        user_id=user_id,
        session_id=session_id,
    )

    logger.info(
        textwrap.dedent(f"""Connecting to room...
    - Room Name: {ctx.room.name}
    - Token: {ctx._info.token}
    - Agent Identity: {agent_identity}
    - Session Config: {session_config}
    - Avatar Config: {avatar_config}""")
    )

    # Build Agent & Virtaul Character Session
    session = AgentSession()
    avatar_engine = AvatarEngine(session_config=session_config, avatar_config=avatar_config)
    avatar_character = avatar_config.character_config.get_plugin()

    # Start Up
    if avatar_character:
        await avatar_character.start(agent_identity, session, room=ctx.room)

    await session.start(
        room=ctx.room,
        agent=avatar_engine,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    # Explicit channel registration bootstrap
    register_builtin_channels()

    input_dispatcher = InputDispatcher(
        room=ctx.room,
        session=session,
    )

    built = None

    async def _handle_adapter_input(envelope, raw_payload):
        # TODO: Support more modalities by dispatching to different handlers based on envelope.modality and built.room_type
        if envelope.modality != "text":
            logger.warning(
                "Unsupported modality for room_type=%s: %s",
                built.room_type if built else "unknown",
                envelope.modality,
            )
            return

        output_envelope = await input_dispatcher.dispatch_text(envelope)
        if built and built.egress:
            await built.egress.send_text(output_envelope, raw_inbound=raw_payload)

    built = build_channel_adapters(
        room=ctx.room,
        session=session,
        on_input=_handle_adapter_input,
    )

    if built.room_type in SUPPORTED_ADAPTER_TYPES and built.ingress and built.egress:
        built.ingress.start()
        logger.info("Attached Channel=%s adapters to room=%s", built.room_type, ctx.room.name)
    else:
        logger.info(
            "No bridged adapters attached for room_type=%s room=%s", built.room_type, ctx.room.name
        )


def main() -> None:
    args = read_args()
    avatar_config: AvatarConfig = get_avatar_args(args)

    opts = agents.WorkerOptions(
        agent_name=avatar_config.avatar_info.avatar_name,
        entrypoint_fnc=partial(entrypoint, avatar_config),
        job_memory_warn_mb=8192,
        job_memory_limit_mb=0,
        num_idle_processes=1,
        load_fnc=worker_load,
        load_threshold=0.9,
        initialize_process_timeout=30,
    )
    agents.cli.run_app(opts)


if __name__ == "__main__":
    main()
