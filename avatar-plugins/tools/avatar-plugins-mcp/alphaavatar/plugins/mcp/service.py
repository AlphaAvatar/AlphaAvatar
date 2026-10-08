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

from typing import TYPE_CHECKING, Any

from alphaavatar.agents.runtime.capability import AvatarCapability
from alphaavatar.agents.runtime.plugin import AvatarModule
from alphaavatar.agents.status import StatusEvent, StatusType
from alphaavatar.agents.tools import ToolBase

from .enums import MCPOp
from .mcp_host import MCPHost
from .schemas import MCPRequest, parse_params

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.agents.status import StatusEmitter


DESCRIPTION = """Use only tools exposed by the configured MCP servers below.
MCP is not a general public-web search tool or a fallback for unrelated capabilities.
First verify that a configured server explicitly covers the request. Prefer a dedicated public-web
tool for prices, news, weather and broad research unless the server advertises that exact scope.
Use tool_search with query to find candidates; an unrelated nearest match is not a valid match.
Do not repeat unrelated searches. Preserve exact tool IDs for tool_call.
top_k is 1-50 (default 8); server_keys restricts exact server names; categories accepts read,
write or unknown. The server's category is descriptive metadata, not permission to execute it.
Use tool_call with params_json mapping exact tool IDs to argument objects. output_mode is raw
(default) or compact. Use refresh_tools only after an advertised tool-set change or missing tool.
monologue is an optional brief user-facing status message, not private reasoning.
Configured MCP server scopes:
{servers}
""".strip()


class MCPToolService(ToolBase):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        servers: dict[str, dict[str, Any]],
        status_emitter: StatusEmitter | None = None,
    ) -> None:
        super().__init__(runtime=runtime, status_emitter=status_emitter)
        self._service = MCPHost(runtime=runtime, servers=servers)
        self.capabilities = (
            AvatarCapability(
                name="MCP",
                description=DESCRIPTION.format(servers=self._service.servers_info),
                input_schema=MCPRequest,
            ),
        )

    async def _start(self) -> None:
        return

    async def _invoke(self, request: MCPRequest) -> Any:
        if self._status is not None:
            self._status.emit_nowait(
                StatusEvent(
                    type=StatusType.TOOL_START,
                    source=AvatarModule.MCP,
                    stage=request.op,
                    message=request.monologue,
                    metadata={"op": request.op.value, "query": request.query},
                )
            )

        if request.op == MCPOp.TOOL_SEARCH:
            return await self._service.search_tools(
                query=request.query,
                top_k=request.top_k,
                server_keys=request.server_keys,
                categories=request.categories,
            )
        if request.op == MCPOp.REFRESH_TOOLS:
            return await self._service.refresh_tools(server_keys=request.server_keys)

        return await self._service.call_tools(
            params=parse_params(request.params_json),
            output_mode=request.output_mode,
        )

    async def _stop(self) -> None:
        await self._service.aclose()
