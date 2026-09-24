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
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.cleanup import wait_for_cleanup
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.agents.runtime.modules.foundation import FoundationRuntime

if TYPE_CHECKING:
    from livekit.agents import AgentSession

    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.runtime import ContextRuntime, SessionRuntime
    from alphaavatar.agents.utils.files.work_dirs import WorkspacePaths


async def create_avatar_runtime(
    *,
    avatar_config: AvatarConfig,
    workspace: WorkspacePaths,
    session: SessionRuntime,
    context: ContextRuntime,
) -> AvatarRuntime:
    async with AsyncExitStack() as resources:
        inference = InferenceExecutor.from_env()
        resources.push_async_callback(inference.close)

        voice = await avatar_config.voice.create_service(inference_executor=inference)
        foundation = FoundationRuntime(voice=voice)
        resources.push_async_callback(foundation.aclose)

        runtime = AvatarRuntime.create(
            workspace=workspace,
            session=session,
            context=context,
            config=avatar_config.runtime,
            inference=inference,
            foundation=foundation,
        )
        resources.pop_all()
        return runtime


async def close_avatar_session(session: AgentSession, runtime: AvatarRuntime) -> None:
    async def close() -> None:
        try:
            await session.aclose()
        finally:
            await runtime.aclose()

    await wait_for_cleanup(asyncio.create_task(close(), name="avatar_session_close"))
