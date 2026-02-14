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
from livekit.agents import mcp


class MCPServerRemote(mcp.MCPServerHTTP):
    def __init__(
        self,
        *,
        url: str,
        **kwargs,
    ) -> None:
        super().__init__(url=url)

    async def list_tools(self) -> list[mcp.MCPTool]:
        # NOTE: We have disabled LiveKit's native chain of injecting MCP as a tool call into the Agent.
        # To prevent Agent performance degradation due to an increase in available MCP tools,
        # and to address the issue of serial tool calls, we provide a unified MCP tool call interface.
        # This supports MCP RAG functionality and parallel tool calls, thereby improving Agent tool call performance.
        return []
