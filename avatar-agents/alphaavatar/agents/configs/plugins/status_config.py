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
    status_plugin: str = Field(
        default="default",
        description="Avatar status plugin to use for intermediate status events.",
    )

    enabled: bool = Field(
        default=True,
        description="Whether to enable intermediate status events.",
    )

    default_language: str = Field(
        default="en",
        description="Default language for status rendering, e.g. en, zh.",
    )

    enable_llm_renderer: bool = Field(
        default=False,
        description="Whether to enable LLM-based status rendering.",
    )

    enable_logger_sink: bool = Field(
        default=True,
        description="Whether to enable logger status sink.",
    )

    enable_livekit_data_sink: bool = Field(
        default=False,
        description="Whether to publish status events through LiveKit data channel.",
    )

    livekit_data_topic: str = Field(
        default="agent.status",
        description="LiveKit data channel topic for status events.",
    )

    status_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the status plugin.",
    )

    def get_plugin(self) -> StatusEmitter:
        status_emitter: StatusEmitter | None = AvatarPlugin.get_avatar_plugin(
            AvatarModule.STATUS,
            self.status_plugin,
            enabled=self.enabled,
            default_language=self.default_language,
            enable_llm_renderer=self.enable_llm_renderer,
            enable_logger_sink=self.enable_logger_sink,
            enable_livekit_data_sink=self.enable_livekit_data_sink,
            livekit_data_topic=self.livekit_data_topic,
            **self.status_init_config,
        )

        if status_emitter is None:
            return StatusEmitter(enabled=False)

        return status_emitter
