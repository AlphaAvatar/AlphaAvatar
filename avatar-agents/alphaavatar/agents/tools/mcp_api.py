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

from alphaavatar.agents import AvatarModule
from alphaavatar.agents.log import logger
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


class MCPHostBase(ABC):
    name = "MCP"
    description = """Execute and orchestrate tools exposed by MCP (Model Context Protocol) servers.

This tool is best used when the task requires:
- Discovering which MCP tool(s) can solve a user request
- Calling multiple MCP tools in parallel to reduce latency
- Coordinating multi-step workflows across different MCP servers
- Unifying access to heterogeneous capabilities (search, data, automation, etc.)

----------------------------------------------------------------------
Available MCP Servers
----------------------------------------------------------------------
{available_mcp_servers}

Each server info is a JSON string with the structure:
- name: string        (server unique name / id)
- title: string       (human-friendly title)
- url: string       (remote server address)
- instruction: string (server instruction / usage guidance)

----------------------------------------------------------------------
Operations
----------------------------------------------------------------------
1) search_tools(query, ctx)
- Purpose:
    Return the most relevant available tools for the given query.
- Behavior:
    Perform tool discovery across currently connected MCP servers and return
    a Top-15 ranked list of tools that best match the query.
- When to use:
    Use this first if you are unsure which MCP tool(s) to call, or if you want
    to present/choose among the best candidates.

2) call_tools(params, ctx)
- Purpose:
    Call multiple MCP tools concurrently in a single request.
- Input:
    params: dict where:
        - key:   tool name (string)
        - value: tool call arguments (dict)
- Behavior:
    Execute all tool calls concurrently (parallel dispatch) and return their results.
- When to use:
    Use this when you already know which tools to call and want to run them in parallel,
    or when a workflow benefits from batching multiple tool calls.

Notes:
- Tool names in params MUST be valid MCP tool identifiers returned by search_tools.
- Each params value MUST match the target tool's input schema.
"""

    def __init__(self, servers_info, *args, **kwargs) -> None:
        super().__init__()
        self.description = self.description.format(available_mcp_servers=servers_info)

    @abstractmethod
    async def search_tools(self, *, query: str, ctx: RunContext) -> Any: ...

    @abstractmethod
    async def call_tools(self, *, params: dict, ctx: RunContext) -> Any: ...


class MCPAPI(ToolBase):
    args_description = """Args:
    op:
        The operation to perform. One of:
        - "tool_search": Search available MCP tools by query.
        - "tool_call": Call one or more MCP tools concurrently.

    query:
        Natural-language description of the needed capability.
        Required for op="tool_search".

    params_json:
        Required for op="tool_call". A JSON string mapping tool_id -> tool_args.
        Example:
            {"clientA.toolX": {"q": "hello"}, "clientB.toolY": {"id": 1}}

    monologue:
        Optional short user-facing status message to show or speak while this
        tool is running. Keep it brief, natural, and in the same language as the
        user. Do not reveal hidden reasoning. Examples:
        - "我找一下合适的工具。"
        - "我用工具看一下。"
        - "I’ll find the right tool."
        - "I’ll use a tool for this."

Expected returns by op (ALL RETURNS ARE STRINGS):
    - tool_search(query) -> str
        A human-readable list of tools relevant to the query, formatted as
        bullet points. Each item is a single-line tool description including
        tool id, input schema, and metadata.

    - tool_call(params_json) -> str
        A Markdown string summarizing the results of concurrent tool execution.
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

    async def invoke(
        self,
        ctx: RunContext,
        op: Literal[
            MCPOp.TOOL_SEARCH,
            MCPOp.TOOL_CALL,
        ],
        query: str | None = None,
        params_json: str | None = None,
        monologue: str | None = None,
    ) -> Any:
        try:
            op = MCPOp(op)
        except ValueError:
            msg = f"Unsupported MCP operation: {op}"
            logger.error(msg)
            raise ToolError(msg)

        self._current_op = op

        try:
            handlers: dict[MCPOp, Callable[[], Awaitable[Any]]] = {
                MCPOp.TOOL_SEARCH: lambda: self._mcp_host.search_tools(
                    query=query,
                    ctx=ctx,
                ),
                MCPOp.TOOL_CALL: lambda: self._call_tools_from_json(
                    params_json=params_json,
                    ctx=ctx,
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

    async def _call_tools_from_json(
        self,
        *,
        params_json: str | None,
        ctx: RunContext,
    ) -> Any:
        if not params_json:
            raise ToolError("MCP tool_call received empty params_json.")

        try:
            params = json.loads(params_json)
        except Exception as e:
            raise ToolError(f"MCP tool_call params_json is not valid JSON: {e}") from e

        if not isinstance(params, dict):
            raise ToolError("MCP tool_call params_json must decode to a JSON object.")

        return await self._mcp_host.call_tools(params=params, ctx=ctx)
