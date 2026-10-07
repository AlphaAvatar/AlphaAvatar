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

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
from alphaavatar.agents.tools import ToolBase
from alphaavatar.agents.utils import resolve_env_placeholders

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.agents.status import StatusEmitter


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

    def model_post_init(self, __context: Any) -> None:
        # Keep worker configuration available before inference-runner preparation.
        # This remains the existing single worker-configuration scope, not per-call state.
        if self.mcp.enabled and self.mcp.plugin is not None and self.mcp.servers:
            os.environ["MCP_VDB_TYPE"] = "lancedb"
            os.environ["MCP_VDB_CONFIG"] = json.dumps(self.mcp.vdb_config)
            os.environ["MCP_SERVERS"] = json.dumps(resolve_env_placeholders(self.mcp.servers))
            importlib.import_module("alphaavatar.plugins.mcp")

    def get_tools(
        self,
        runtime: AvatarRuntime,
        *,
        status_emitter: StatusEmitter | None = None,
    ) -> tuple[ToolBase, ...]:
        tools = []
        selections = (
            (AvatarModule.DEEPRESEARCH, "deepresearch", self.deepresearch),
            (AvatarModule.RAG, "rag", self.rag),
        )
        for module, package, config in selections:
            if config.plugin is None:
                continue
            importlib.import_module(f"alphaavatar.plugins.{package}")
            tool = AvatarModulePlugin.create(
                module,
                config.plugin,
                runtime=runtime,
                init_config=config.init_config,
                status_emitter=status_emitter,
            )
            if not isinstance(tool, ToolBase):
                raise TypeError(f"Tool plugin {package} must return ToolBase")

            tools.append(tool)

        if self.mcp.enabled and self.mcp.plugin is not None:
            if not self.mcp.servers:
                raise ValueError("Enabled MCP requires at least one configured server")
            importlib.import_module("alphaavatar.plugins.mcp")

            tool = AvatarModulePlugin.create(
                AvatarModule.MCP,
                self.mcp.plugin,
                runtime=runtime,
                init_config=self.mcp.init_config,
                servers=resolve_env_placeholders(self.mcp.servers),
                status_emitter=status_emitter,
            )
            if not isinstance(tool, ToolBase):
                raise TypeError("MCP plugin must return ToolBase")
            tools.append(tool)

        return tuple(tools)
