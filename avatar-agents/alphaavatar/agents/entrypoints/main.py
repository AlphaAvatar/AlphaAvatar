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
import asyncio
import contextlib
import json
import os
import textwrap
from functools import partial

from livekit import agents, api
from livekit.agents import AgentSession, room_io
from livekit.agents.job import AutoSubscribe
from livekit.plugins import noise_cancellation

from alphaavatar.agents.avatar import AvatarEngine
from alphaavatar.agents.avatar.patches import AvatarServer
from alphaavatar.agents.configs import AvatarConfig, get_avatar_args, read_args
from alphaavatar.agents.constants import DEFAULT_CONTEXT_VALUE
from alphaavatar.agents.env import init_env
from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime import ContextRuntime, InteractionMethod, SessionRuntime
from alphaavatar.agents.utils.id_utils import get_session_id, get_user_id
from alphaavatar.agents.utils.time_utils import TimeStamp, build_time_context_from_metadata

from .channels.bootstrap import register_builtin_channels
from .channels.factory import build_channel_adapters
from .io.dispatcher import InputDispatcher
from .io.envelopes import InputEnvelope
from .schema.room_type import SUPPORTED_ADAPTER_TYPES, detect_room_type
from .schema.session_mode import SessionMode, resolve_session_mode
from .schema.session_type import resolve_session_type

init_env()


def get_max_session_seconds() -> int:
    raw_value = os.getenv("ALPHAAVATAR_MAX_SESSION_SECONDS", "1800")
    try:
        return int(raw_value)
    except ValueError:
        logger.warning(
            "Invalid ALPHAAVATAR_MAX_SESSION_SECONDS=%r, fallback to 1800",
            raw_value,
        )
        return 1800


MAX_SESSION_SECONDS = get_max_session_seconds()


async def force_close_room_after_timeout(
    *,
    room_name: str,
    session: AgentSession,
) -> None:
    if MAX_SESSION_SECONDS <= 0:
        logger.info("Max session duration watchdog disabled for room=%s", room_name)
        return

    try:
        await asyncio.sleep(MAX_SESSION_SECONDS)

        logger.warning(
            "Max session duration reached. Closing room=%s after %s seconds",
            room_name,
            MAX_SESSION_SECONDS,
        )

        # Close the AgentSession first.
        session.shutdown(drain=True)

        # Then force-delete the room so all participants are disconnected.
        lkapi = api.LiveKitAPI()
        try:
            await lkapi.room.delete_room(
                api.DeleteRoomRequest(room=room_name),
            )
            logger.warning("Deleted room after max duration: %s", room_name)
        finally:
            await lkapi.aclose()

    except asyncio.CancelledError:
        logger.info("Max session duration watchdog cancelled for room=%s", room_name)
        raise
    except Exception:
        logger.exception("Failed to force close room=%s", room_name)


def log_background_task_result(task: asyncio.Task) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        exc = task.exception()
        if exc:
            logger.error(
                "Background task failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )


def worker_load(worker) -> float:
    return min(len(worker.active_jobs) / 5.0, 1.0)


def build_room_options(
    session_mode: SessionMode,
    participant_identity: str | None = None,
) -> room_io.RoomOptions:
    kwargs = {
        # RoomOptions-supported inputs.
        "text_input": session_mode.text_input_enabled,
        "video_input": session_mode.video_input_enabled,
        # RoomOptions-supported outputs.
        "text_output": session_mode.text_output_enabled,
        "audio_output": session_mode.audio_output_enabled,
        # Important lifecycle controls.
        # Close AgentSession when the linked user disconnects.
        "close_on_disconnect": True,
        # Delete the LiveKit room when AgentSession is closed.
        # Otherwise the room may remain active until all participants leave.
        "delete_room_on_close": True,
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

    if participant_identity:
        kwargs["participant_identity"] = participant_identity

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
    room_identity = participant.identity

    room_type = detect_room_type(ctx.room)
    session_type = resolve_session_type(room_type, participant_metadata)
    session_mode = resolve_session_mode(session_type)

    user_id = participant_metadata.get("user_id", get_user_id())
    session_id = participant_metadata.get("session_id", get_session_id(room_type))
    timestamp: TimeStamp = build_time_context_from_metadata(participant_metadata)

    # Build Session Config
    session_runtime = SessionRuntime(
        session_id=session_id,
    )
    session_runtime.add_participant(
        user_id=user_id,
        room_identity=room_identity,
        room_type=room_type.value,
        timestamp=timestamp,
        metadata=participant_metadata,
        primary=True,
    )

    visual_input_enabled = session_mode.video_input_enabled and avatar_config.vision.input.enabled

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

    context_runtime = ContextRuntime(
        interaction_method=interaction_method,
        timestamp=timestamp,
        global_behavior_rules=participant_metadata.get(
            "global_behavior_rules",
            DEFAULT_CONTEXT_VALUE,
        ),
        extra_context={
            "room_name": ctx.room.name,
            "agent_identity": agent_identity,
            "session_id": session_id,
        },
    )

    logger.info(
        textwrap.dedent(f"""Connecting to room...
    - Agent Identity: {agent_identity}
    - Token: {ctx._info.token}
    - Room Name: {ctx.room.name}
    - Room Type: {room_type}
    - Session Id: {session_id}
    - Session Type: {session_type}
    - Session Mode: {session_mode}
    - Avatar Config: {avatar_config}""")
    )

    # Build Agent & Virtual Character Session
    session = AgentSession()

    @ctx.room.on("participant_connected")
    def on_participant_connected(connected_participant):
        logger.info(
            "Participant connected room=%s identity=%s",
            ctx.room.name,
            connected_participant.identity,
        )

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(disconnected_participant):
        logger.info(
            "Participant disconnected room=%s identity=%s linked_identity=%s",
            ctx.room.name,
            disconnected_participant.identity,
            room_identity,
        )

        if disconnected_participant.identity == room_identity:
            logger.info(
                "Linked participant disconnected. AgentSession should close via close_on_disconnect. room=%s",
                ctx.room.name,
            )

    avatar_engine = AvatarEngine(
        session_runtime=session_runtime,
        avatar_config=avatar_config,
        context_runtime=context_runtime,
    )

    # Bind room before session.start so status sinks can publish early events.
    avatar_engine.bind_livekit_room(ctx.room)

    # Start character
    avatar_character = avatar_config.character.get_plugin()
    if avatar_character:
        await avatar_character.start(agent_identity, session, room=ctx.room)

    # Start Agent Session
    await session.start(
        room=ctx.room,
        agent=avatar_engine,
        room_options=build_room_options(
            session_mode,
            participant_identity=room_identity,
        ),
    )

    _max_duration_task = asyncio.create_task(
        force_close_room_after_timeout(
            room_name=ctx.room.name,
            session=session,
        )
    )
    _max_duration_task.add_done_callback(log_background_task_result)

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
        agent_name=avatar_config.avatar.name,
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
