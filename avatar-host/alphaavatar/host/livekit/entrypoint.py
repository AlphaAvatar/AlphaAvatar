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
from __future__ import annotations

import asyncio
import json
import os
from functools import partial

from livekit import agents
from livekit.agents.job import AutoSubscribe

from alphaavatar.agents.avatar import AvatarEngine
from alphaavatar.agents.avatar.patches import AvatarServer
from alphaavatar.agents.configs import AvatarConfig, get_avatar_args, read_args
from alphaavatar.agents.constants import DEFAULT_CONTEXT_VALUE
from alphaavatar.agents.env import init_env
from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime import InteractionMethod, SessionRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import prepare_inference_runners
from alphaavatar.agents.utils.files.work_dirs import WorkspacePaths, prepare_user_path
from alphaavatar.agents.utils.id_utils import get_session_id, get_user_id
from alphaavatar.agents.utils.time import build_user_time_context
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import LifecycleComponent
from alphaavatar.host.bootstrap import create_avatar_runtime
from alphaavatar.rtc.livekit.audio.input import LiveKitAudioInput
from alphaavatar.rtc.livekit.audio.output import LiveKitTransientAudioOutput
from alphaavatar.rtc.livekit.status.output import LiveKitStatusOutput
from alphaavatar.rtc.livekit.text import LiveKitTextInput
from alphaavatar.rtc.livekit.transcript.output import LiveKitTranscriptOutput
from alphaavatar.rtc.livekit.video.input import LiveKitVideoInput

from .connection import LiveKitConnection
from .lifecycle import close_session_execution
from .session import resolve_session_mode, resolve_session_type

init_env()


def get_max_session_seconds() -> int:
    raw = os.getenv("ALPHAAVATAR_MAX_SESSION_SECONDS", "1800")
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid ALPHAAVATAR_MAX_SESSION_SECONDS=%r; using 1800", raw)
        return 1800


def worker_load(worker) -> float:
    return min(len(worker.active_jobs) / 5.0, 1.0)


async def entrypoint(avatar_config: AvatarConfig, ctx: agents.JobContext) -> None:
    # Character providers still require an SDK AgentSession. Never create a hidden
    # second generator or silently disable an explicitly configured character.
    if avatar_config.character.plugin is not None:
        raise ValueError(
            "Native Engine currently requires character.plugin=null; migrate the character transport first"
        )
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)

    # Get metadata.
    agent_identity = ctx.token_claims().identity
    participant = await ctx.wait_for_participant()
    metadata = json.loads(participant.metadata) if participant.metadata else {}
    if not isinstance(metadata, dict):
        raise ValueError("Participant metadata must be a JSON object")

    # Native-client context label, not a channel dispatch key.
    room_type = "alphaavatar_app"
    session_type = resolve_session_type(metadata)
    mode = resolve_session_mode(session_type)

    user_id = metadata.get("user_id", get_user_id())
    session_id = metadata.get("session_id", get_session_id())
    user_time = build_user_time_context(metadata)

    # Build Runtime Components
    workspace = WorkspacePaths.from_env()
    user_path = workspace.users.get(user_id)
    prepare_user_path(user_path)

    session = SessionRuntime(
        session_id=session_id,
    )
    session.add_participant(
        participant_identity=participant.identity,
        user_id=user_id,
        room_id=ctx.room.name,
        room_type=room_type,
        user_time=user_time,
        user_path=user_path,
        metadata=metadata,
        primary=True,
    )

    visual = mode.video_input_enabled and avatar_config.vision.enabled
    state = StateRuntime(
        interaction_method=InteractionMethod(
            room_type=room_type,
            session_type=session_type.value,
            text_input=mode.text_input_enabled,
            audio_input=mode.audio_input_enabled,
            video_input=visual,
            audio_output=mode.audio_output_enabled,
            text_output=mode.text_output_enabled,
            notes=[
                "Adapt response style to the active room/session modality.",
                "Do not invent visual details when current visual evidence is unavailable.",
            ],
        ),
        global_behavior_rules=metadata.get("global_behavior_rules", DEFAULT_CONTEXT_VALUE),
        extra_context={
            "room_name": ctx.room.name,
            "agent_identity": agent_identity,
            "session_id": session_id,
        },
    )
    runtime = await create_avatar_runtime(
        avatar_config=avatar_config, workspace=workspace, session=session, state=state
    )
    engine: AvatarEngine | None = None
    connection: LiveKitConnection | None = None
    orphan_close: asyncio.Task[None] | None = None

    async def shutdown() -> None:
        nonlocal orphan_close
        if connection is not None:
            await connection.aclose()
        else:
            if orphan_close is None:
                orphan_close = asyncio.create_task(
                    close_session_execution(runtime, engine=engine),
                    name="avatar_unbound_runtime_close",
                )
            await wait_for_cleanup(orphan_close)

    ctx.add_shutdown_callback(shutdown)
    try:
        if mode.audio_output_enabled and runtime.foundation.voice.tts is None:
            raise ValueError("The selected session requires audio output but no TTS is configured")
        engine = AvatarEngine(avatar_config=avatar_config, runtime=runtime)
        outputs: list[LifecycleComponent] = [
            LiveKitStatusOutput(
                room=ctx.room,
                output_runtime=runtime.output,
                action_topic=avatar_config.status.action_topic,
            )
        ]

        audio_output = None
        if mode.audio_output_enabled:
            audio_output = LiveKitTransientAudioOutput(
                room=ctx.room,
                output_runtime=runtime.output,
                sample_rate=runtime.foundation.voice.tts.sample_rate,
                num_channels=runtime.foundation.voice.tts.num_channels,
            )
            outputs.append(audio_output)
        if mode.text_output_enabled:
            outputs.append(
                LiveKitTranscriptOutput(
                    room=ctx.room,
                    output_runtime=runtime.output,
                    track_sid=(lambda: audio_output.track_sid)
                    if audio_output is not None
                    else None,
                )
            )

        inputs: list[LifecycleComponent] = []
        if mode.audio_input_enabled:
            inputs.append(
                LiveKitAudioInput(
                    room=ctx.room,
                    perception=runtime.perception,
                    sample_rate=16000,
                    num_channels=1,
                    frame_size_ms=avatar_config.runtime.perception.audio_frame_size_ms,
                )
            )
        if visual:
            inputs.append(
                LiveKitVideoInput(
                    room=ctx.room,
                    perception=runtime.perception,
                    publish_interval_sec=avatar_config.runtime.perception.video_publish_interval_sec,
                )
            )

        text_input = None
        if mode.text_input_enabled:
            text_input = LiveKitTextInput(
                room=ctx.room,
                clock=runtime.perception.clock,
                session_id=session_id,
                participant_identities=frozenset((participant.identity,)),
                submit=engine.submit_input,
                max_streams=avatar_config.runtime.engine.max_pending_admissions,
                max_bytes=avatar_config.runtime.engine.max_input_bytes,
            )
            inputs.append(text_input)

        connection = LiveKitConnection(
            ctx=ctx,
            runtime=runtime,
            engine=engine,
            participant_identity=participant.identity,
            inputs=inputs,
            outputs=outputs,
            text_input=text_input,
            max_duration=get_max_session_seconds(),
        )
        await connection.start()
        logger.info(
            "Native Avatar connected room=%s session_id=%s session_type=%s",
            ctx.room.name,
            session_id,
            session_type.value,
        )
    except BaseException as original:
        try:
            await shutdown()
        except BaseException as cleanup:
            raise original from cleanup
        raise


def main() -> None:
    avatar_config = get_avatar_args(read_args())
    prepare_inference_runners(avatar_config)

    opts = agents.worker.ServerOptions(
        agent_name=avatar_config.avatar.name,
        entrypoint_fnc=partial(entrypoint, avatar_config),
        job_memory_warn_mb=8192,
        job_memory_limit_mb=0,
        num_idle_processes=4,
        load_fnc=worker_load,
        load_threshold=0.9,
        initialize_process_timeout=60,
        shutdown_process_timeout=180,
    )
    # Job/process hosting remains SDK-backed; no SDK Agent, AgentSession or generation nodes remain here.
    agents.cli.run_app(AvatarServer.from_server_options(opts))


if __name__ == "__main__":
    main()
