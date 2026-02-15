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
import asyncio

from livekit.agents import utils

from alphaavatar.agents.tools import MCPHostBase
from alphaavatar.agents.utils import AsyncLoopThread

from .log import logger
from .mcp_server_remote import MCPServerRemote
from .mcp_tool import MCPTool


class MCPHost(MCPHostBase):
    # NOTE: We have disabled LiveKit's native chain of injecting MCP as a tool call into the Agent.
    # To prevent Agent performance degradation due to an increase in available MCP tools,
    # and to address the issue of serial tool calls, we provide a unified MCP tool call interface.
    # This supports MCP RAG functionality and parallel tool calls, thereby improving Agent tool call performance.

    def __init__(self, urls: list[str], **kwargs) -> None:
        self._clients: list[MCPServerRemote] | None = None
        self._mcp_tools: dict[str, MCPTool] | None = None

        self._loop_thread = AsyncLoopThread(name="raganything-loop")
        self._loop_thread.submit(self._initialize(urls))

        super().__init__(description=self._get_tools_description(), **kwargs)

    async def _initialize(self, urls: list[str]):
        # STEP 1: Initialize MCPServerRemotes in parallel
        self._clients = [MCPServerRemote(url=url) for url in urls]

        @utils.log_exceptions(logger=logger)
        async def _initialize_client(client: MCPServerRemote) -> None:
            if not client.initialized:
                await client.initialize()

        await asyncio.gather(
            *(_initialize_client(c) for c in self._clients), return_exceptions=True
        )

        # STEP 2: List tools from all clients in parallel and aggregate them
        @utils.log_exceptions(logger=logger)
        async def _list_mcp_tools(
            mcp_server: MCPServerRemote,
        ) -> list[MCPTool]:
            return await mcp_server.list_tools()

        gathered = await asyncio.gather(
            *(_list_mcp_tools(s) for s in self._clients),
            return_exceptions=True,
        )
        self._mcp_tools: dict[str, MCPTool] = {}
        for tools in gathered:
            if isinstance(tools, list):
                for tool in tools:
                    self._mcp_tools[tool._tool_id] = tool

    def _get_tools_description(self, tool_ids: list[str] | None = None) -> str:
        if self._mcp_tools is None:
            return "MCPHost with uninitialized tools"

        tool_list = "\n".join(
            f"- {tool.description}"
            for tool in self._mcp_tools.values()
            if tool_ids is None or tool._tool_id in tool_ids
        )
        return f"MCPHost with the following tools:\n{tool_list}"
