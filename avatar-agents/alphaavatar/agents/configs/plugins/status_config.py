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

import importlib

from pydantic import BaseModel, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.status import StatusEmitter

importlib.import_module("alphaavatar.plugins.status")


class StatusConfig(BaseModel):
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
        description="LiveKit data topic for structured status action events.",
    )

    text_topic: str = Field(
        default="agent.status.text",
        description="LiveKit data topic for user-facing status text events.",
    )

    init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the status plugin.",
    )

    def get_plugin(self) -> StatusEmitter:
        status_emitter: StatusEmitter | None = AvatarPlugin.get_avatar_plugin(
            AvatarModule.STATUS,
            self.plugin,
            enabled=self.enabled,
            action_topic=self.action_topic,
            text_topic=self.text_topic,
            **self.init_config,
        )

        if status_emitter is None:
            return StatusEmitter(enabled=False)

        return status_emitter
