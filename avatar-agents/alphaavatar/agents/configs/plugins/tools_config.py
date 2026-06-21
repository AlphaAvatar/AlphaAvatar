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
import json
import os
from typing import TYPE_CHECKING, Any

from livekit.agents import llm
from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.log import logger
from alphaavatar.agents.tools import ToolBase
from alphaavatar.agents.utils import resolve_env_placeholders

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import SessionRuntime
    from alphaavatar.agents.status import StatusEmitter


importlib.import_module("alphaavatar.plugins.deepresearch")
importlib.import_module("alphaavatar.plugins.mcp")
importlib.import_module("alphaavatar.plugins.rag")


class ToolPluginConfig(BaseModel):
    """Common config for a tool plugin."""

    model_config = ConfigDict(extra="forbid")

    plugin: str | None = Field(
        default="default",
        description="Tool plugin name. Set to null to disable this tool.",
    )
    init_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Custom initialization parameters for this tool plugin.",
    )


class MCPConfig(BaseModel):
    """Configuration for MCP tool integration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Whether to enable the MCP plugin.",
    )
    plugin: str | None = Field(
        default="default",
        description="MCP tool plugin name. Set to null to disable MCP tool creation.",
    )
    init_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Custom initialization parameters for the MCP plugin.",
    )
    vdb_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Custom initialization parameters for the MCP VDB backend "
            "(e.g. host, port, url, api_key, prefer_grpc, embedding)."
        ),
    )
    servers: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Mapping of MCP server identifiers to their configuration objects.",
    )


class ToolsConfig(BaseModel):
    """Configuration for AlphaAvatar tools."""

    model_config = ConfigDict(extra="forbid")

    deepresearch: ToolPluginConfig = Field(default_factory=ToolPluginConfig)
    rag: ToolPluginConfig = Field(default_factory=ToolPluginConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    def model_post_init(self, __context):
        if self.mcp.enabled and len(self.mcp.servers) > 0:
            os.environ["MCP_VDB_TYPE"] = "lancedb"
            os.environ["MCP_VDB_CONFIG"] = json.dumps(self.mcp.vdb_config)

            mcp_servers = resolve_env_placeholders(self.mcp.servers)
            os.environ["MCP_SERVERS"] = json.dumps(mcp_servers)

    def get_tools(
        self,
        session_runtime: SessionRuntime,
        *,
        status_emitter: StatusEmitter | None = None,
    ) -> list[llm.FunctionTool | llm.RawFunctionTool]:
        """Returns the available tools based on the configuration."""
        tools: list[llm.FunctionTool | llm.RawFunctionTool] = []

        # DeepResearch Tool
        if self.deepresearch.plugin is not None:
            deepresearch_tool: ToolBase | None = AvatarPlugin.get_avatar_plugin(
                AvatarModule.DEEPRESEARCH,
                self.deepresearch.plugin,
                session_runtime=session_runtime,
                status_emitter=status_emitter,
                deepresearch_init_config=self.deepresearch.init_config,
            )
            if deepresearch_tool:
                tools.append(deepresearch_tool.tool)

        # RAG Tool
        if self.rag.plugin is not None:
            rag_tool: ToolBase | None = AvatarPlugin.get_avatar_plugin(
                AvatarModule.RAG,
                self.rag.plugin,
                session_runtime=session_runtime,
                status_emitter=status_emitter,
                rag_init_config=self.rag.init_config,
            )
            if rag_tool:
                tools.append(rag_tool.tool)

        # MCP Tool
        if not self.mcp.enabled:
            return tools

        if len(self.mcp.servers) == 0:
            logger.warning("No MCP server URLs provided while MCP is enabled.")
            return tools

        if self.mcp.plugin is None:
            logger.warning("MCP is enabled but tools.mcp.plugin is null.")
            return tools

        mcp_tool: ToolBase | None = AvatarPlugin.get_avatar_plugin(
            AvatarModule.MCP,
            self.mcp.plugin,
            session_runtime=session_runtime,
            status_emitter=status_emitter,
            mcp_init_config=self.mcp.init_config,
        )
        if mcp_tool:
            tools.append(mcp_tool.tool)

        return tools
