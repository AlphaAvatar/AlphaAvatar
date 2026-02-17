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
import json
import time
from typing import Any

from livekit.agents import RunContext, utils
from livekit.agents.llm.tool_context import ToolError

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

    def __init__(self, servers: dict[str, dict], **kwargs) -> None:
        self._clients: list[MCPServerRemote] | None = None
        self._mcp_tools: dict[str, MCPTool] | None = None

        self._loop_thread = AsyncLoopThread(name="mcp-loop")
        self._loop_thread.submit(self._initialize(servers))

        super().__init__(servers_info=self._get_servers_info(), **kwargs)

    async def _initialize(self, servers: dict[str, dict]):
        # STEP 1: Initialize MCPServerRemotes in parallel
        self._clients = [MCPServerRemote(**servers[name]) for name in servers]

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

    def _get_servers_info(self) -> str:
        if self._clients is None:
            return "MCPHost with uninitialized servers"

        info_list = "\n".join(f"- {client.info}" for client in self._clients)
        return f"MCPHost with the following servers:\n{info_list}"

    async def search_tools(self, *, query: str, ctx: RunContext) -> str:
        logger.info(f"[MCPHost] search_tools called with query: {query}")

        if self._mcp_tools is None:
            return "MCPHost with uninitialized tools"

        # TODO: search tools base on query

        tool_list = "\n".join(f"- {tool.description}" for tool in self._mcp_tools.values())
        return f"MCPHost with the following tools for query ({query}):\n{tool_list}"

    async def call_tools(self, *, params: dict, ctx: RunContext) -> str:
        call_start = time.time()
        logger.info(f"[MCPHost] call_tools invoked with {len(params) if params else 0} tools")

        if self._mcp_tools is None:
            logger.warning("[MCPHost] call_tools called before initialization")
            return "MCPHost with uninitialized tools"

        if not params:
            logger.warning("[MCPHost] Empty params received")
            return "MCPHost TOOL_CALL received empty params"

        # 1) Pre-check: Does tool exist?
        missing = [tool_id for tool_id in params.keys() if tool_id not in self._mcp_tools]
        if missing:
            logger.error(f"[MCPHost] Missing tools requested: {missing}")
            missing_list = "\n".join(f"- {tid}" for tid in missing)
            available_hint = "\n".join(f"- {tid}" for tid in sorted(self._mcp_tools.keys())[:50])
            return (
                "### MCP TOOL_CALL error\n"
                "Some tools are not available in this MCPHost.\n\n"
                f"**Missing tools:**\n{missing_list}\n\n"
                f"**Available tools (partial):**\n{available_hint}\n"
            )

        # 2) Concurrent calls (preserving input order)
        ordered_items: list[tuple[str, Any]] = list(params.items())

        async def _call_one(tool_id: str, raw_args: Any) -> Any:
            tool = self._mcp_tools[tool_id]
            tool_start = time.time()

            logger.info(f"[MCPHost] Calling tool: {tool_id}, args: {raw_args}")

            if raw_args is None:
                raw_args = {}

            if not isinstance(raw_args, dict):
                logger.error(f"[MCPHost] Invalid args type for {tool_id}")
                raise ToolError(f"Invalid params for tool '{tool_id}': expected dict")

            try:
                result = await tool.call(raw_args)
                logger.info(
                    f"[MCPHost] Tool {tool_id} completed in {time.time() - tool_start:.2f}s"
                )
                return result
            except Exception as e:
                logger.exception(
                    f"[MCPHost] Tool {tool_id} failed after {time.time() - tool_start:.2f}s"
                )
                raise ToolError(f"Tool {tool_id} failed because: {e}")

        results = []
        for tool_id, raw_args in ordered_items:
            try:
                results.append(await _call_one(tool_id, raw_args))
            except Exception as e:
                results.append(e)

        success_count = sum(1 for r in results if not isinstance(r, Exception))
        error_count = len(results) - success_count
        logger.info(
            f"[MCPHost] call_tools finished in {time.time() - call_start:.2f}s | "
            f"Success: {success_count} | Errors: {error_count}"
        )

        # 3) Markdown summary output
        lines: list[str] = []
        lines.append("### MCP TOOL_CALL results")
        lines.append("")
        lines.append(f"- Total tools requested: **{len(ordered_items)}**")
        lines.append("")

        for (tool_id, raw_args), res in zip(ordered_items, results, strict=False):
            lines.append(f"#### {tool_id}")
            lines.append("")
            lines.append("**Args:**")
            lines.append("```json")
            try:
                lines.append(json.dumps(raw_args or {}, ensure_ascii=False, indent=2))
            except Exception:
                lines.append(json.dumps({"_repr_": repr(raw_args)}, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

            if isinstance(res, Exception):
                lines.append("**Status:** ❌ Error")
                lines.append("")
                lines.append("```text")
                lines.append(str(res))
                lines.append("```")
            else:
                lines.append("**Status:** ✅ OK")
                lines.append("")
                # TODO: MCPTool.call() currently returns a JSON string (or a JSON list string).
                # To avoid misclassification, it's displayed as text here; if you're sure it's always JSON, you can change it to ```json`
                lines.append("```text")
                lines.append(res if isinstance(res, str) else json.dumps(res, ensure_ascii=False))
                lines.append("```")

            lines.append("")  # spacer

        return "\n".join(lines)
