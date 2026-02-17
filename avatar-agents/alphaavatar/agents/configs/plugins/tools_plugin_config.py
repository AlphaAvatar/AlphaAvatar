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
from alphaavatar.agents.log import logger
from alphaavatar.agents.tools import ToolBase
from alphaavatar.agents.utils import resolve_env_placeholders

if TYPE_CHECKING:
    from alphaavatar.agents.configs import SessionConfig


importlib.import_module("alphaavatar.plugins.deepresearch")
importlib.import_module("alphaavatar.plugins.mcp")
importlib.import_module("alphaavatar.plugins.rag")


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

    enable_mcp: bool = Field(
        default=False,
        description="Whether to enable the MCP plugin.",
    )
    mcp_servers: dict[str, dict] = Field(
        default={},
        description=(
            "Mapping of MCP server identifiers to their configuration objects. "
            "Each key represents a logical MCP server name, and the value is a "
            "dictionary containing connection parameters such as `url` and optional "
            "`headers`.\n\n"
            "Example:\n"
            "{\n"
            '  "livekit-docs": {\n'
            '    "url": "https://docs.livekit.io/mcp"\n'
            "  },\n"
            '  "github-mcp": {\n'
            '    "url": "https://api.githubcopilot.com/mcp/",\n'
            '    "headers": {\n'
            '      "Authorization": "Bearer <GITHUB_PAT>"\n'
            "    }\n"
            "  }\n"
            "}\n\n"
            "The configuration object is passed directly to the MCPServerRemote "
            "constructor when initializing remote MCP connections."
        ),
    )
    mcp_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the MCP plugin.",
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
            deepresearch_init_config=self.deepresearch_init_config,
            working_dir=session_config.user_path.data_dir,
        )
        if deepresearch_tool:
            tools.append(deepresearch_tool.tool)

        # RAG Tool
        rag_tool: ToolBase | None = AvatarPlugin.get_avatar_plugin(
            AvatarModule.RAG,
            self.rag_tool,
            rag_init_config=self.rag_init_config,
            working_dir=session_config.user_path.data_dir,
        )
        if rag_tool:
            tools.append(rag_tool.tool)

        if not self.enable_mcp:
            return tools

        # For remote MCP servers
        if len(self.mcp_servers) == 0:
            logger.warning("No MCP server URLs provided while MCP is enabled.")
            return tools

        mcp_servers = resolve_env_placeholders(self.mcp_servers)
        mcp_tool: ToolBase | None = AvatarPlugin.get_avatar_plugin(
            AvatarModule.MCP,
            "default",
            servers=mcp_servers,
            mcp_init_config=self.mcp_init_config,
            working_dir=session_config.user_path.data_dir,
        )
        if mcp_tool:
            tools.append(mcp_tool.tool)

        return tools
