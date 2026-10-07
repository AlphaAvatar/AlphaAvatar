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
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.agents.runtime.modules.foundation import FoundationRuntime
from alphaavatar.core.cleanup import wait_for_cleanup

if TYPE_CHECKING:
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.runtime import SessionRuntime, StateRuntime
    from alphaavatar.agents.utils.files.work_dirs import WorkspacePaths


async def create_avatar_runtime(
    *,
    avatar_config: AvatarConfig,
    workspace: WorkspacePaths,
    session: SessionRuntime,
    state: StateRuntime,
) -> AvatarRuntime:
    resources = AsyncExitStack()
    try:
        inference = InferenceExecutor.from_env()

        # build avatar runtime
        resources.push_async_callback(inference.close)
        runtime = AvatarRuntime.create(
            workspace=workspace,
            session=session,
            state=state,
            config=avatar_config.runtime,
            inference=inference,
        )
        # The partial runtime already owns Output and Inference, even before binding Foundation.
        resources.pop_all()
        resources.push_async_callback(runtime.aclose)

        # build foundation runtime
        context = avatar_config.context.get_plugin(runtime=runtime, avatar_config=avatar_config)
        resources.push_async_callback(context.aclose)
        voice = await avatar_config.voice.get_plugin(inference_executor=inference)
        resources.push_async_callback(voice.aclose)
        loop = avatar_config.loop.get_plugin(runtime=runtime)
        resources.push_async_callback(loop.aclose)
        foundation = FoundationRuntime(
            context=context,
            loop=loop,
            voice=voice,
        )
        resources.push_async_callback(foundation.aclose)

        runtime.bind_foundation(foundation)
        resources.pop_all()
        resources.push_async_callback(runtime.aclose)
    except BaseException:
        await wait_for_cleanup(
            asyncio.create_task(resources.aclose(), name="avatar_bootstrap_rollback")
        )
        raise

    resources.pop_all()
    return runtime
