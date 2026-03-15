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

from livekit.agents import RunContext
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
        self._init_future = self._loop_thread.submit_future(self._initialize(servers))
        self._init_error: Exception | None = None

        super().__init__(servers_info=self._build_config_servers_info(servers), **kwargs)

    def _build_config_servers_info(self, servers: dict[str, dict]) -> str:
        lines = []
        for name, cfg in servers.items():
            url = cfg.get("url", "unknown")
            instruction = cfg.get("instruction") or cfg.get("instruction") or ""
            lines.append(f"- name={name}, url={url}, instruction={instruction}")
        return "MCPHost configured servers:\n" + "\n".join(lines)

    async def _ensure_initialized(self) -> None:
        async with self._init_lock:
            if self._init_future is None:
                return

            future = self._init_future
            self._init_future = None

            try:
                await asyncio.wrap_future(future)
            except Exception as e:
                self._init_error = e
                logger.exception("[MCPHost] initialization failed")

    async def _initialize(self, servers: dict[str, dict]):
        self._clients = [MCPServerRemote(**servers[name]) for name in servers]
        self._mcp_tools = {}

        # STEP 1: Initialize MCPServerRemotes in parallel
        ready_clients: list[MCPServerRemote] = []

        async def _initialize_client(client: MCPServerRemote) -> None:
            try:
                if not client.initialized:
                    await client.initialize()
                ready_clients.append(client)
                logger.info("[MCPHost] MCP client ready: %s", client.url)
            except Exception:
                logger.exception("[MCPHost] Failed to initialize MCP client: %s", client.url)

        await asyncio.gather(*(_initialize_client(c) for c in self._clients))

        self._clients = ready_clients

        # STEP 2: List tools from all clients in parallel and aggregate them
        async def _list_mcp_tools(mcp_server: MCPServerRemote) -> list[MCPTool]:
            try:
                return await mcp_server.list_tools()
            except Exception:
                logger.exception(
                    "[MCPHost] Failed to list tools from MCP server: %s", mcp_server.url
                )
                return []

        gathered = await asyncio.gather(*(_list_mcp_tools(s) for s in self._clients))

        for tools in gathered:
            for tool in tools:
                self._mcp_tools[tool._tool_id] = tool

        logger.info(
            "[MCPHost] initialized clients=%d tools=%d",
            len(self._clients),
            len(self._mcp_tools),
        )

    async def search_tools(self, *, query: str, ctx: RunContext) -> str:
        await self._ensure_initialized()

        logger.info(f"[MCPHost] search_tools called with query: {query}")

        if self._mcp_tools is None:
            return "MCPHost with uninitialized tools"

        # TODO: search tools base on query

        tool_list = "\n".join(f"- {tool.description}" for tool in self._mcp_tools.values())
        return f"MCPHost with the following tools for query ({query}):\n{tool_list}"

    async def call_tools(self, *, params: dict, ctx: RunContext) -> str:
        await self._ensure_initialized()

        call_start = time.perf_counter()
        logger.info("[MCPHost] call_tools count=%d", len(params) if params else 0)

        if self._mcp_tools is None:
            logger.warning("[MCPHost] call_tools called before initialization")
            return "MCPHost with uninitialized tools"

        if not params:
            logger.warning("[MCPHost] Empty params received")
            return "MCPHost TOOL_CALL received empty params"

        # 1) Pre-check: Does tool exist?
        missing = [tool_id for tool_id in params.keys() if tool_id not in self._mcp_tools]
        if missing:
            logger.warning("[MCPHost] missing tools: %s", missing)
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
            tool_start = time.perf_counter()

            logger.debug(
                "[MCPHost] Calling tool=%s args=%s",
                tool_id,
                raw_args,
            )

            if raw_args is None:
                raw_args = {}

            if not isinstance(raw_args, dict):
                raise ToolError(f"Invalid params for tool '{tool_id}': expected dict")

            try:
                result = await tool.call(raw_args)
                logger.info(
                    "[MCPHost] tool=%s elapsed=%.2fs status=ok",
                    tool_id,
                    time.perf_counter() - tool_start,
                )
                return result
            except Exception as e:
                logger.exception(
                    "[MCPHost] tool=%s elapsed=%.2fs status=error",
                    tool_id,
                    time.perf_counter() - tool_start,
                )
                raise ToolError(f"Tool {tool_id} failed because: {e}")

        results = await asyncio.gather(
            *(_call_one(tool_id, raw_args) for tool_id, raw_args in ordered_items),
            return_exceptions=True,
        )

        success_count = sum(1 for r in results if not isinstance(r, Exception))
        error_count = len(results) - success_count
        logger.info(
            "[MCPHost] call_tools finished elapsed=%.2fs success=%d error=%d",
            time.perf_counter() - call_start,
            success_count,
            error_count,
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

    async def aclose(self) -> None:
        if self._clients:
            for client in self._clients:
                try:
                    await client.aclose()
                except Exception:
                    logger.exception("[MCPHost] Failed to close MCP client: %s", client.url)

        self._loop_thread.stop()
