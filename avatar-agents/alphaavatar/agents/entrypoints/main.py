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

from livekit import agents
from livekit.agents import AgentSession, room_io
from livekit.agents.job import AutoSubscribe
from livekit.plugins import noise_cancellation

from alphaavatar.agents.avatar import AvatarEngine
from alphaavatar.agents.avatar.context.runtime_context import (
    AvatarRuntimeContext,
    InteractionMethod,
    TimeContext,
)
from alphaavatar.agents.avatar.patches import AvatarServer
from alphaavatar.agents.configs import AvatarConfig, SessionConfig, get_avatar_args, read_args
from alphaavatar.agents.constants import DEFAULT_CONTEXT_VALUE
from alphaavatar.agents.env import init_env
from alphaavatar.agents.log import logger
from alphaavatar.agents.utils import get_session_id, get_user_id
from alphaavatar.agents.utils.time_utils import build_time_context_from_metadata

from .channels.bootstrap import register_builtin_channels
from .channels.factory import build_channel_adapters
from .io.dispatcher import InputDispatcher
from .io.envelopes import InputEnvelope
from .schema.room_type import SUPPORTED_ADAPTER_TYPES, detect_room_type
from .schema.session_mode import SessionMode, resolve_session_mode
from .schema.session_type import resolve_session_type

init_env()


def worker_load(worker) -> float:
    return min(len(worker.active_jobs) / 5.0, 1.0)


def build_room_options(session_mode: SessionMode) -> room_io.RoomOptions:
    kwargs = {
        # RoomOptions-supported inputs.
        "text_input": session_mode.text_input_enabled,
        "video_input": session_mode.video_input_enabled,
        # RoomOptions-supported outputs.
        "text_output": session_mode.text_output_enabled,
        "audio_output": session_mode.audio_output_enabled,
    }

    if session_mode.audio_input_enabled:
        if session_mode.enable_noise_cancellation:
            kwargs["audio_input"] = room_io.AudioInputOptions(
                noise_cancellation=noise_cancellation.BVC(),
            )
        else:
            kwargs["audio_input"] = True
    else:
        kwargs["audio_input"] = False

    return room_io.RoomOptions(**kwargs)


async def publish_ready_signal(ctx: agents.JobContext, room_type: str) -> None:
    """
    Explicitly notify bridge that the agent is fully ready to receive inbound channel messages.
    Only publish ready for bridged adapter room types such as whatsapp.
    """
    if room_type not in SUPPORTED_ADAPTER_TYPES:
        return

    payload = {
        "status": "ready",
        "room_type": room_type,
        "room_name": ctx.room.name,
    }

    await ctx.room.local_participant.publish_data(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        topic=f"{room_type}.ready",
        reliable=True,
    )

    logger.info(
        "Published ready signal topic=%s room=%s",
        f"{room_type}.ready",
        ctx.room.name,
    )


async def entrypoint(avatar_config: AvatarConfig, ctx: agents.JobContext):
    # Wait connecting...

    # Important:
    # auto_subscribe controls whether the worker receives remote media tracks at the
    # LiveKit transport layer. AgentSession room_options only controls which
    # modalities are consumed by the agent pipeline.
    #
    # Do not use SUBSCRIBE_NONE for voice/video rooms, otherwise microphone tracks
    # will never reach STT/VAD even if room_options.audio_input=True.
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)

    # Get Metadata
    agent_identity = ctx.token_claims().identity
    participant = await ctx.wait_for_participant()
    participant_metadata = json.loads(participant.metadata) if participant.metadata else {}

    room_type = detect_room_type(ctx.room)
    session_type = resolve_session_type(room_type, participant_metadata)
    session_mode = resolve_session_mode(session_type)

    user_id = participant_metadata.get("user_id", get_user_id())
    session_id = participant_metadata.get("session_id", get_session_id(room_type))
    time_data = build_time_context_from_metadata(participant_metadata)

    session_config = SessionConfig(
        user_id=user_id,
        session_id=session_id,
    )

    visual_input_enabled = (
        session_mode.video_input_enabled and avatar_config.vision_config.vision_input_enabled
    )

    interaction_method = InteractionMethod(
        room_type=room_type.value,
        session_type=session_type.value,
        text_input=session_mode.text_input_enabled,
        audio_input=session_mode.audio_input_enabled,
        video_input=visual_input_enabled,
        audio_output=session_mode.audio_output_enabled,
        text_output=session_mode.text_output_enabled,
        notes=[
            "Adapt response style to the active room/session modality.",
            "If visual input is enabled but no visual frame is available in the current turn, do not invent visual details.",
        ],
    )

    time_context = TimeContext(
        current_time=time_data["current_time"],
        current_timezone=time_data["current_timezone"],
        timezone_source=time_data["timezone_source"],
        last_session_timezone=time_data["last_session_timezone"],
        last_session_time=time_data["last_session_time"],
    )

    runtime_context = AvatarRuntimeContext(
        interaction_method=interaction_method,
        time_context=time_context,
        global_behavior_rules=participant_metadata.get(
            "global_behavior_rules",
            DEFAULT_CONTEXT_VALUE,
        ),
        extra_context={
            "room_name": ctx.room.name,
            "agent_identity": agent_identity,
            "user_id": user_id,
            "session_id": session_id,
        },
    )

    logger.info(
        textwrap.dedent(f"""Connecting to room...
    - Room Name: {ctx.room.name}
    - Token: {ctx._info.token}
    - Agent Identity: {agent_identity}
    - Room Type: {room_type}
    - Session Type: {session_type}
    - Session Mode: {session_mode}
    - Session Config: {session_config}
    - Avatar Config: {avatar_config}""")
    )

    # Build Agent & Virtual Character Session
    session = AgentSession()
    avatar_engine = AvatarEngine(
        session_config=session_config,
        avatar_config=avatar_config,
        runtime_context=runtime_context,
    )

    # Bind room before session.start so status sinks can publish early events.
    avatar_engine.bind_livekit_room(ctx.room)

    # Start character
    avatar_character = avatar_config.character_config.get_plugin()
    if avatar_character:
        await avatar_character.start(agent_identity, session, room=ctx.room)

    # Start Agent Session
    await session.start(
        room=ctx.room,
        agent=avatar_engine,
        room_options=build_room_options(session_mode),
    )

    # Explicit channel registration bootstrap
    register_builtin_channels()

    input_dispatcher = InputDispatcher(
        room=ctx.room,
        session=session,
    )

    built = None

    async def _handle_adapter_input(envelope: InputEnvelope, raw_payload):
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

        # IMPORTANT:
        # Only publish ready after:
        # 1) session.start() completed
        # 2) adapters were built
        # 3) ingress.start() completed
        await publish_ready_signal(ctx, built.room_type)

    else:
        logger.info(
            "No bridged adapters attached for room_type=%s room=%s", built.room_type, ctx.room.name
        )


def main() -> None:
    args = read_args()
    avatar_config: AvatarConfig = get_avatar_args(args)

    opts = agents.worker.ServerOptions(
        agent_name=avatar_config.avatar_info.avatar_name,
        entrypoint_fnc=partial(entrypoint, avatar_config),
        job_memory_warn_mb=8192,
        job_memory_limit_mb=0,
        num_idle_processes=4,
        load_fnc=worker_load,
        load_threshold=0.9,
        initialize_process_timeout=60,
    )
    server = AvatarServer.from_server_options(opts)
    agents.cli.run_app(server)


if __name__ == "__main__":
    main()
