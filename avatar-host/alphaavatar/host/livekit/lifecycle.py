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
from typing import TYPE_CHECKING

from alphaavatar.agents.runtime.cleanup import wait_for_cleanup

if TYPE_CHECKING:
    from livekit.agents import AgentSession

    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.host.lifecycle import HostSessionLifecycle


async def close_session_execution(
    session: AgentSession,
    runtime: AvatarRuntime,
    *,
    lifecycle: HostSessionLifecycle | None = None,
) -> None:
    """Close SDK activity, Host-owned components, then the session-owned runtime."""

    async def close() -> None:
        try:
            await session.aclose()
        finally:
            try:
                if lifecycle is not None:
                    await lifecycle.aclose()
            finally:
                await runtime.aclose()

    await wait_for_cleanup(asyncio.create_task(close(), name="avatar_session_close"))
