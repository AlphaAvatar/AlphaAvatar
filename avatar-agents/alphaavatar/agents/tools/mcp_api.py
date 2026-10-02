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
import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any, Literal

from livekit.agents import RunContext
from livekit.agents.llm import ToolError

from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.agents.runtime.plugin import AvatarModule
from alphaavatar.agents.status import (
    StatusEmitter,
    StatusEvent,
    StatusPriority,
    StatusType,
)

from .base import ToolBase


class MCPOp(StrEnum):
    TOOL_SEARCH = "tool_search"
    TOOL_CALL = "tool_call"
    REFRESH_TOOLS = "refresh_tools"


class MCPOutputMode(StrEnum):
    COMPACT = "compact"
    RAW = "raw"


MCP_TOOL_CATEGORIES = ("read", "write", "unknown")
MCP_TOP_K_RANGE = (1, 50)


class MCPHostBase(ABC):
    name = "MCP"
    description = """Use tools exposed by the configured MCP servers listed below.

Hard scope boundary:
- MCP is limited to the listed servers and their explicitly advertised
  capabilities.
- MCP is not a general public-web search tool.
- MCP is not a generic fallback when another top-level tool already directly
  covers the request.
- Do not use MCP for public stock prices, market data, general news, weather,
  recent public information, or broad web research unless one of the configured
  MCP servers explicitly advertises that exact capability.
- Before calling MCP, verify that the request clearly matches at least one
  configured server scope.
- If no configured server directly matches, choose another top-level tool.
- Do not repeatedly call tool_search for the same request.

Configured MCP server scopes:
----------------------------------------------------------------------
{available_mcp_servers}
----------------------------------------------------------------------

Operations:
1. tool_search
   Search only within the tools exposed by the configured MCP servers.

   Use this operation only after establishing that the request belongs to a
   configured MCP server's scope. It is not a general capability or web search.

2. tool_call
   Call one or more exact MCP tool identifiers returned by tool_search.

3. refresh_tools
   Reload tools from the configured MCP servers without restarting.

   Use this only when a server's tool set has changed, or when a tool that
   should exist is reported as missing. It is not needed for normal use.

Rules:
- Call only tools whose description and server instruction directly match the
  user's request.
- A nearest search result is not necessarily a valid match.
- If returned candidates are unrelated, do not call them and do not repeat the
  MCP search. Use another top-level tool.
"""

    def __init__(self, *, runtime: AvatarRuntime, servers_info: str, **kwargs) -> None:
        super().__init__()
        self.runtime = runtime
        self.description = self.description.format(available_mcp_servers=servers_info)

    @property
    def inference_executor(self) -> InferenceExecutor:
        return self.runtime.inference

    @abstractmethod
    async def search_tools(
        self,
        *,
        query: str,
        ctx: RunContext,
        top_k: int = 8,
        server_keys: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> Any: ...

    @abstractmethod
    async def refresh_tools(
        self,
        *,
        ctx: RunContext,
        server_keys: list[str] | None = None,
    ) -> Any: ...

    @abstractmethod
    async def call_tools(
        self,
        *,
        params: dict,
        ctx: RunContext,
        output_mode: str = MCPOutputMode.RAW,
    ) -> Any: ...


class MCPAPI(ToolBase):
    args_description = """Args:
    op:
        - "tool_search": Search tools inside configured MCP servers.
        - "tool_call": Call one or more exact MCP tool identifiers.
        - "refresh_tools": Reload tools from configured MCP servers.

    query:
        Required for op="tool_search".

        The query must describe a capability clearly belonging to one of the
        configured MCP server scopes. Do not use it for general public-web
        lookup or to discover arbitrary capabilities outside those servers.

    top_k:
        Optional for op="tool_search". Number of candidates to return (1-50, default 8).

    server_keys:
        Optional for op="tool_search" and op="refresh_tools". Exact configured MCP
        server names to search or refresh. Omit to use all configured servers.

    categories:
        Optional for op="tool_search". Restrict candidates by tool category:
        "read" (read-only tools), "write" (tools that may change state) and
        "unknown" (server did not declare it). Omit to search all categories.

    output_mode:
        Optional for op="tool_call". "raw" (default) returns full results;
        "compact" truncates long per-tool results and omits echoed arguments.

    params_json:
        Required for op="tool_call". JSON string mapping tool_id to arguments.

        Example:
            {"github.search_code": {"query": "AvatarRuntime"}}

    monologue:
        Optional brief user-facing status message.

Expected returns:
    - tool_search: nearest MCP candidates; candidates still require a direct
      domain match before use
    - tool_call: results from the selected MCP tools
    - refresh_tools: per-server summary of added, removed, and updated tools
"""

    def __init__(
        self,
        mcp_host: MCPHostBase,
        *,
        status_emitter: StatusEmitter | None = None,
    ) -> None:
        super().__init__(
            name=mcp_host.name,
            description=mcp_host.description + "\n\n" + self.args_description,
            status_emitter=status_emitter,
        )

        self._mcp_host = mcp_host
        self._current_op: MCPOp | None = None

    def _emit_op_status(
        self,
        *,
        op: MCPOp,
        status_type: StatusType,
        query: str | None = None,
        params_json: str | None = None,
        monologue: str | None = None,
    ) -> None:
        metadata: dict[str, Any] = {
            "op": op.value,
        }

        if query is not None:
            metadata["query"] = query

        if params_json is not None:
            metadata["has_params_json"] = True

            try:
                params = json.loads(params_json)
                if isinstance(params, dict):
                    metadata["tool_count"] = len(params)
                    metadata["tool_names"] = list(params.keys())[:10]
            except Exception:
                metadata["params_json_parseable"] = False

        self.emit_status_nowait(
            StatusEvent(
                type=status_type,
                source=AvatarModule.MCP,
                stage=op,
                message=monologue,
                priority=StatusPriority.NORMAL,
                metadata=metadata,
            )
        )

    def _status_source(self):
        return AvatarModule.MCP

    def _status_stage(self):
        return self._current_op or "tool_error"

    @staticmethod
    def _validate_server_keys(op: MCPOp, server_keys: list[str] | None) -> None:
        if server_keys is not None and (
            not isinstance(server_keys, list)
            or not server_keys
            or any(not isinstance(key, str) or not key for key in server_keys)
        ):
            raise ToolError(f"MCP {op.value} server_keys must be a nonempty list of names.")

    async def _call_tools_from_json(
        self,
        *,
        params_json: str | None,
        ctx: RunContext,
        output_mode: str = MCPOutputMode.RAW,
    ) -> Any:
        if not params_json:
            raise ToolError("MCP tool_call received empty params_json.")

        try:
            params = json.loads(params_json)
        except Exception as e:
            raise ToolError(f"MCP tool_call params_json is not valid JSON: {e}") from e

        if not isinstance(params, dict):
            raise ToolError("MCP tool_call params_json must decode to a JSON object.")

        return await self._mcp_host.call_tools(params=params, ctx=ctx, output_mode=output_mode)

    async def invoke(
        self,
        ctx: RunContext,
        op: Literal[
            MCPOp.TOOL_SEARCH,
            MCPOp.TOOL_CALL,
            MCPOp.REFRESH_TOOLS,
        ],
        query: str | None = None,
        params_json: str | None = None,
        monologue: str | None = None,
        top_k: int = 8,
        server_keys: list[str] | None = None,
        categories: list[str] | None = None,
        output_mode: str = MCPOutputMode.RAW,
    ) -> Any:
        try:
            op = MCPOp(op)
        except ValueError:
            msg = f"Unsupported MCP operation: {op}"
            logger.error(msg)
            raise ToolError(msg)

        self._current_op = op

        try:
            if op == MCPOp.TOOL_SEARCH:
                if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 50:
                    raise ToolError("MCP tool_search top_k must be an integer from 1 to 50.")
                self._validate_server_keys(op, server_keys)
                if categories is not None and (
                    not isinstance(categories, list)
                    or not categories
                    or any(c not in MCP_TOOL_CATEGORIES for c in categories)
                ):
                    raise ToolError(
                        "MCP tool_search categories must be a nonempty list of "
                        f"{MCP_TOOL_CATEGORIES}."
                    )
            elif op == MCPOp.TOOL_CALL:
                if output_mode not in tuple(MCPOutputMode):
                    modes = tuple(m.value for m in MCPOutputMode)
                    raise ToolError(f"MCP tool_call output_mode must be one of {modes}.")
            elif op == MCPOp.REFRESH_TOOLS:
                self._validate_server_keys(op, server_keys)

            handlers: dict[MCPOp, Callable[[], Awaitable[Any]]] = {
                MCPOp.TOOL_SEARCH: lambda: self._mcp_host.search_tools(
                    query=query,
                    ctx=ctx,
                    top_k=top_k,
                    server_keys=server_keys,
                    categories=categories,
                ),
                MCPOp.TOOL_CALL: lambda: self._call_tools_from_json(
                    params_json=params_json,
                    ctx=ctx,
                    output_mode=output_mode,
                ),
                MCPOp.REFRESH_TOOLS: lambda: self._mcp_host.refresh_tools(
                    ctx=ctx,
                    server_keys=server_keys,
                ),
            }

            self._emit_op_status(
                op=op,
                status_type=StatusType.TOOL_START,
                query=query,
                params_json=params_json,
                monologue=monologue,
            )

            result = await handlers[op]()

        finally:
            self._current_op = None

        return result
