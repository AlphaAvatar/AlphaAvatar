# Copyright 2026 AlphaAvatar project
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
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.host.execution.execution import HostExecution
from alphaavatar.host.sessions.factory import create_session_backend
from alphaavatar.host.sessions.manager import SessionManager
from alphaavatar.host.sessions.mode import resolve_session_mode, resolve_session_type
from alphaavatar.host.sessions.schemas import SessionContext, SessionEnd, SessionRequest

if TYPE_CHECKING:
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.runtime import AvatarRuntime, SessionRuntime, StateRuntime
    from alphaavatar.agents.utils.files.work_dirs import WorkspacePaths
    from alphaavatar.host.configs.application import ApplicationConfig
    from alphaavatar.host.sessions.attachment import SessionAttachment


async def create_avatar_runtime(
    *,
    avatar_config: AvatarConfig,
    workspace: WorkspacePaths,
    session: SessionRuntime,
    state: StateRuntime,
) -> AvatarRuntime:
    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.agents.runtime.inference import InferenceExecutor
    from alphaavatar.agents.runtime.modules.foundation import FoundationRuntime

    resources = AsyncExitStack()
    try:
        inference = InferenceExecutor.from_env()

        # 1.AvatarRuntime
        resources.push_async_callback(inference.close)
        runtime = AvatarRuntime.create(
            workspace=workspace,
            session=session,
            state=state,
            config=avatar_config.runtime,
            inference=inference,
        )
        resources.pop_all()
        resources.push_async_callback(runtime.aclose)

        # 2.Context Plugin
        context = avatar_config.context.get_plugin(runtime=runtime, avatar_config=avatar_config)
        resources.push_async_callback(context.aclose)

        # 3.Voice Plugin
        voice = await avatar_config.voice.get_plugin(inference_executor=inference)
        resources.push_async_callback(voice.aclose)

        # 4.Loop Plugin
        loop = avatar_config.loop.get_plugin(runtime=runtime)
        resources.push_async_callback(loop.aclose)

        # 5.Foundation Runtime
        foundation = FoundationRuntime(context=context, loop=loop, voice=voice)

        # 6.Clear
        resources.pop_all()
        resources.push_async_callback(runtime.aclose)
        resources.push_async_callback(foundation.aclose)
        runtime.bind_foundation(foundation)
        resources.pop_all()
        resources.push_async_callback(runtime.aclose)
        await loop.initialize()
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        if not loop.ready:
            raise RuntimeError("Loop initialization finished without becoming ready")
    except BaseException as original:
        try:
            await wait_for_cleanup(
                asyncio.create_task(resources.aclose(), name="avatar_bootstrap_rollback")
            )
        except BaseException as cleanup:
            raise original from cleanup
        raise
    resources.pop_all()
    return runtime


async def create_execution(config: ApplicationConfig, access: SessionContext) -> HostExecution:
    from alphaavatar.agents.avatar import AvatarEngine
    from alphaavatar.agents.constants import DEFAULT_CONTEXT_VALUE
    from alphaavatar.agents.runtime import InteractionMethod, SessionRuntime, StateRuntime
    from alphaavatar.agents.utils.files.work_dirs import WorkspacePaths, prepare_user_path
    from alphaavatar.agents.utils.id_utils import get_session_id, get_user_id
    from alphaavatar.agents.utils.time import build_user_time_context

    # Metadata
    avatar, metadata = config.avatar, access.metadata
    user_id = metadata.get("user_id", get_user_id())
    session_id = metadata.get("session_id", get_session_id())
    if not all(isinstance(value, str) and 0 < len(value) <= 256 for value in (user_id, session_id)):
        raise ValueError(
            "User and session identifiers must be nonempty strings of at most 256 characters"
        )

    # Session
    session_type = resolve_session_type(metadata)
    mode = resolve_session_mode(session_type)
    workspace = WorkspacePaths.from_env()
    user_path = workspace.users.get(user_id)
    prepare_user_path(user_path)

    # Runtime
    session = SessionRuntime(session_id=session_id)
    session.add_participant(
        participant_identity=access.participant_identity,
        user_id=user_id,
        room_id=access.room_name,
        room_type=access.room_type,
        user_time=build_user_time_context(metadata),
        user_path=user_path,
        metadata=metadata,
        primary=True,
    )
    state = StateRuntime(
        interaction_method=InteractionMethod(
            room_type=access.room_type,
            session_type=session_type.value,
            text_input=mode.text_input_enabled,
            audio_input=mode.audio_input_enabled,
            video_input=mode.video_input_enabled and avatar.vision.enabled,
            audio_output=mode.audio_output_enabled,
            text_output=mode.text_output_enabled,
            notes=[
                "Adapt response style to the active room/session modality.",
                "Do not invent visual details when current visual evidence is unavailable.",
            ],
        ),
        global_behavior_rules=metadata.get("global_behavior_rules", DEFAULT_CONTEXT_VALUE),
        extra_context={
            "room_name": access.room_name,
            "agent_identity": access.agent_identity,
            "session_id": session_id,
        },
    )
    runtime = await create_avatar_runtime(
        avatar_config=avatar,
        workspace=workspace,
        session=session,
        state=state,
    )

    # Engine
    resources = AsyncExitStack()
    resources.push_async_callback(runtime.aclose)
    try:
        engine = AvatarEngine(
            avatar_config=avatar,
            runtime=runtime,
        )
        resources.push_async_callback(engine.on_stop)
        execution = HostExecution(
            runtime=runtime,
            engine=engine,
        )
        resources.pop_all()
        return execution
    except BaseException as original:
        try:
            await wait_for_cleanup(
                asyncio.create_task(resources.aclose(), name="execution_assembly_rollback")
            )
        except BaseException as cleanup:
            raise original from cleanup
        raise


async def run_execution(
    config: ApplicationConfig,
    request: SessionRequest,
    *,
    stop: asyncio.Event,
    ready: Callable[[], Awaitable[None]],
) -> str:
    if request.backend != config.host.rtc.backend:
        raise ValueError("Execution request does not match the configured backend")

    backend = create_session_backend(config.host.rtc)
    resources = AsyncExitStack()
    resources.push_async_callback(backend.aclose)
    tasks: list[asyncio.Task] = []
    connection_ended = asyncio.Event()
    connection_end: SessionEnd | None = None

    async def assemble() -> tuple[HostExecution, SessionAttachment, SessionManager]:
        connection = backend.connection(request)
        resources.push_async_callback(connection.on_stop)

        async def watch_connection() -> None:
            nonlocal connection_end
            connection_end = await connection.wait_ended()
            connection_ended.set()

        tasks.append(asyncio.create_task(watch_connection(), name="execution_connection_watch"))
        await connection.on_start()

        execution = await create_execution(config, connection.context)
        resources.push_async_callback(execution.aclose)
        attachment = await backend.attachment(
            connection=connection, execution=execution, config=config
        )

        # Transfer connection ownership to the attachment; settle adapters before the Runtime.
        resources.pop_all()
        resources.push_async_callback(backend.aclose)
        resources.push_async_callback(execution.aclose)
        resources.push_async_callback(attachment.aclose)

        manager = SessionManager()
        manager.register(execution, attachment)

        resources.pop_all()
        resources.push_async_callback(backend.aclose)
        resources.push_async_callback(execution.aclose)
        resources.push_async_callback(manager.aclose)

        await manager.start(attachment.attachment_id)
        return execution, attachment, manager

    async def body() -> str:
        starting = asyncio.create_task(assemble(), name="execution_assembly")
        stopping = asyncio.create_task(stop.wait(), name="execution_stop_request")
        disconnected = asyncio.create_task(connection_ended.wait(), name="execution_connection_end")
        tasks.extend((starting, stopping, disconnected))

        done, _ = await asyncio.wait(
            (starting, stopping, disconnected), return_when=asyncio.FIRST_COMPLETED
        )
        if starting in done:
            execution, attachment, _ = await starting
        elif disconnected in done:
            assert connection_end is not None
            return connection_end.reason
        else:
            return "host_shutdown"

        if stop.is_set():
            return "host_shutdown"
        if connection_end is not None:
            return connection_end.reason

        await ready()

        failed = asyncio.create_task(execution.wait_failed(), name="execution_failure_watch")
        ended = asyncio.create_task(attachment.wait_ended(), name="execution_attachment_end")
        waiting = [failed, ended, stopping]
        duration = config.host.execution.max_session_seconds
        timer = None
        if duration:
            timer = asyncio.create_task(asyncio.sleep(duration), name="execution_duration")
            waiting.append(timer)

        tasks.extend(task for task in waiting if task is not stopping)
        done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
        if failed in done:
            await failed

        if ended in done:
            end = await ended
            if end.attachment_id != attachment.attachment_id:
                raise RuntimeError("Session end belongs to another attachment")
            if end.failed:
                raise RuntimeError(f"Session failed: {end.reason}")
            if not config.host.execution.ends_execution():
                raise RuntimeError("Unsupported execution retention policy")
            return end.reason

        return "max_session_duration" if timer in done else "host_shutdown"

    async def cleanup() -> None:
        # Cancel assembly first; it can still be transferring resource ownership.
        for task in tuple(tasks):
            if not task.done():
                task.cancel()
        await asyncio.gather(*tuple(tasks), return_exceptions=True)
        await resources.aclose()

    try:
        reason = await body()
    except BaseException as original:
        try:
            await wait_for_cleanup(asyncio.create_task(cleanup(), name="execution_cleanup"))
        except BaseException as error:
            raise original from error
        raise
    await wait_for_cleanup(asyncio.create_task(cleanup(), name="execution_cleanup"))
    return reason
