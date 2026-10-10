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

from importlib import import_module
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
from alphaavatar.agents.status import StatusBase

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime


class StatusConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin: str = Field(
        default="default",
        description="Avatar status plugin to use for intermediate status events.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether to enable intermediate status events.",
    )
    action_topic: str = Field(
        default="agent.status.action",
        description="Avatar data topic for structured status action events.",
    )
    init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the status plugin.",
    )

    def get_plugin(self, *, runtime: AvatarRuntime) -> StatusBase:
        import_module("alphaavatar.plugins.status")
        plugin = AvatarModulePlugin.create(
            AvatarModule.STATUS,
            self.plugin,
            runtime=runtime,
            enabled=self.enabled,
            init_config=self.init_config,
        )

        if not isinstance(plugin, StatusBase):
            raise TypeError("Status plugins must return StatusBase")

        return plugin
