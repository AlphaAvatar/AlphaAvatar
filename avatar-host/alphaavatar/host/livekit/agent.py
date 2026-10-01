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

from collections.abc import Sequence
from typing import TYPE_CHECKING

from alphaavatar.agents.avatar import AvatarEngine
from alphaavatar.core.lifecycle import SessionLifecycle
from alphaavatar.host.lifecycle import HostSessionLifecycle

if TYPE_CHECKING:
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.runtime import AvatarRuntime


class LiveKitHostedAgent(AvatarEngine):
    """Temporary SDK hook bridge; remove with the LiveKit Agents execution path."""

    def __init__(
        self,
        *,
        avatar_config: AvatarConfig,
        runtime: AvatarRuntime,
        inputs: Sequence[SessionLifecycle] = (),
        outputs: Sequence[SessionLifecycle] = (),
    ) -> None:
        super().__init__(avatar_config=avatar_config, runtime=runtime)
        self._host_lifecycle = HostSessionLifecycle(engine=self, inputs=inputs, outputs=outputs)

    @property
    def host_lifecycle(self) -> HostSessionLifecycle:
        return self._host_lifecycle

    async def on_enter(self) -> None:
        await self._host_lifecycle.start()

    async def on_exit(self) -> None:
        await self._host_lifecycle.aclose()
