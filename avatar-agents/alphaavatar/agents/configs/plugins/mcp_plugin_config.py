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
from typing import TYPE_CHECKING

from livekit.agents import mcp
from pydantic import BaseModel, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.log import logger

if TYPE_CHECKING:
    from alphaavatar.agents.configs import SessionConfig


importlib.import_module("alphaavatar.plugins.mcp")


class MCPConfig(BaseModel):
    enable_mcp: bool = Field(
        default=False,
        description="Whether to enable the MCP plugin.",
    )
    mcp_server_urls: list[str] = Field(
        default=[],
        description="List of MCP server URLs to connect to.",
    )
    mcp_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the MCP plugin.",
    )

    def model_post_init(self, __context): ...

    def get_mcps(self, session_config: SessionConfig) -> list[mcp.MCPServerHTTP]:
        """Returns the available tools based on the configuration."""
        mcps = []

        if not self.enable_mcp:
            return mcps

        # For remote MCP servers
        if len(self.mcp_server_urls) == 0:
            logger.warning("No MCP server URLs provided while MCP is enabled.")
            return mcps

        for url in self.mcp_server_urls:
            mcp_i: mcp.MCPServerHTTP | None = AvatarPlugin.get_avatar_plugin(
                AvatarModule.MCP,
                "default_remote",
                url=url,
                mcp_init_config=self.mcp_init_config,
            )
            if mcp_i is not None:
                mcps.append(mcp_i)

        return mcps
