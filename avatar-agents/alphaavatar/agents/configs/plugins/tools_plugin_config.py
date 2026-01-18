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
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from livekit.agents import llm
from pydantic import BaseModel, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.tools import RAGAPI, ToolBase

if TYPE_CHECKING:
    from alphaavatar.agents.configs import SessionConfig


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

    rag_tool: str = Field(
        default="default",
        description="Avatar RAG tool plugin to use for agent.",
    )
    rag_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the RAG tool plugin.",
    )

    def model_post_init(self, __context): ...

    def get_tools(
        self, session_config: SessionConfig
    ) -> list[llm.FunctionTool | llm.RawFunctionTool]:
        """Returns the available tools based on the configuration."""
        tools = []

        # DeepResearch Tool
        deepresearch_tool: ToolBase | None = AvatarPlugin.get_avatar_plugin(
            AvatarModule.DEEPRESEARCH,
            self.deepresearch_tool,
            character_init_config=self.deepresearch_init_config,
            working_dir=session_config.user_path.data_dir,
        )
        if deepresearch_tool:
            tools.append(deepresearch_tool.tool)

        # RAG Tool
        rag_tool: RAGAPI | None = AvatarPlugin.get_avatar_plugin(
            AvatarModule.RAG,
            self.rag_tool,
            character_init_config=self.rag_init_config,
            working_dir=session_config.user_path.data_dir,
        )
        if rag_tool:
            tools.append(rag_tool.tool)

        return tools
