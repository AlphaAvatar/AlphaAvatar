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
import importlib
import os

from pydantic import BaseModel, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.avatar.character import VirtialCharacterSession

importlib.import_module("alphaavatar.plugins.character")


class VirtualCharacterConfig(BaseModel):
    """Configuration for the Virtual Character plugin used in the agent."""

    # Character plugin config
    plugin: str | None = Field(
        default=None,
        description="Avatar Virtual Character plugin to use for agent visually represents.",
    )
    init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the Virtual Character plugin.",
    )

    def model_post_init(self, __context):
        if self.plugin is not None:
            os.environ["ALPHAAVATAR_CHARACTER_NAME"] = self.plugin

    def get_plugin(self) -> VirtialCharacterSession | None:
        """Returns the Character plugin instance based on the configuration."""
        return AvatarPlugin.get_avatar_plugin(
            AvatarModule.CHARACTER,
            self.plugin,
            character_init_config=self.init_config,
        )
