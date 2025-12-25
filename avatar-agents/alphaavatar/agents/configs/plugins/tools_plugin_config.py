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

from livekit.agents import llm
from pydantic import BaseModel, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.tools import ToolBase

importlib.import_module("alphaavatar.plugins.deepresearch")


class ToolsConfig(BaseModel):
    deepresearch_tool: str = Field(
        default="default",
        description="Avatar deepresearch tool plugin to use for agent.",
    )
    deepresearch_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the deepresearch tool plugin.",
    )

    def model_post_init(self, __context): ...

    def get_tools(self) -> list[llm.FunctionTool | llm.RawFunctionTool]:
        """Returns the available tools based on the configuration."""
        tools = []

        deepresearch_tool: ToolBase | None = AvatarPlugin.get_avatar_plugin(
            AvatarModule.DEEPRESEARCH,
            self.deepresearch_tool,
            character_init_config=self.deepresearch_init_config,
        )
        if deepresearch_tool:
            tools.append(deepresearch_tool.tool)

        return tools
