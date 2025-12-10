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

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.tools import ToolBase

importlib.import_module("alphaavatar.plugins.deepsearch")


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class ToolsConfig:
    deepresearch_tool: str = Field(
        default="default",
        description="Avatar deepresearch tool plugin to use for agent.",
    )
    deepresearch_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the deepresearch tool plugin.",
    )

    def __post_init__(self): ...

    def get_plugin(self) -> list[ToolBase]:
        """Returns the Persona plugin instance based on the configuration."""
        deepresearch_tool = AvatarPlugin.get_avatar_plugin(
            AvatarModule.DEEPSEARCH,
            self.deepresearch_tool,
            character_init_config=self.deepresearch_init_config,
        )

        return [deepresearch_tool]
