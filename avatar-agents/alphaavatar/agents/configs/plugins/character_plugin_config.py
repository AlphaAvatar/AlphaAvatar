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

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.sessions import VirtialCharacterSession

importlib.import_module("alphaavatar.plugins.character")


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class VirtualCharacterConfig:
    """Configuration for the Virtual Character plugin used in the agent."""

    # Character plugin config
    character_plugin: str = Field(
        default="default",
        description="Avatar Virtual Character plugin to use for agent visually represents.",
    )
    character_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the Virtual Character plugin.",
    )

    def __post_init__(self):
        # Set CHARACRER_NAME
        os.environ["CHARACRER_NAME"] = self.character_plugin

    def get_plugin(self) -> VirtialCharacterSession:
        """Returns the Character plugin instance based on the configuration."""
        return AvatarPlugin.get_avatar_plugin(
            AvatarModule.CHARACTER,
            self.character_plugin,
            character_init_config=self.character_init_config,
        )
