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

from alphaavatar.core.cleanup import wait_for_cleanup

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.core.lifecycle import LifecycleComponent
    from alphaavatar.host.execution import HostExecution


async def close_session_execution(
    runtime: AvatarRuntime,
    *,
    exection: HostExecution | None = None,
    engine: LifecycleComponent | None = None,
) -> None:
    """Stop Host consumers, then release the runtime, even if either step fails."""

    async def close() -> None:
        errors: list[Exception] = []
        operations = (
            (exection.aclose,)
            if exection is not None
            else (engine.on_stop,)
            if engine is not None
            else ()
        )
        for operation in (*operations, runtime.aclose):
            try:
                await operation()
            except asyncio.CancelledError as error:
                failure = RuntimeError("Session cleanup cancelled itself")
                failure.__cause__ = error
                errors.append(failure)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Native session execution cleanup failed", errors)

    await wait_for_cleanup(asyncio.create_task(close(), name="avatar_session_close"))
