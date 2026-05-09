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

import json
import os
from typing import Any

from livekit.agents import RunContext
from livekit.agents.job import get_job_context

from alphaavatar.agents.tools import MCPHostBase
from alphaavatar.agents.tools.mcp_api import MCPOp

from .log import logger


class MCPHost(MCPHostBase):
    def __init__(self, servers: dict[str, dict], **kwargs) -> None:
        super().__init__(servers_info=self._build_config_servers_info(servers), **kwargs)
        self._servers = servers

    @property
    def inference_method(self) -> str:
        method = os.getenv("MCP_INFERENCE_METHOD")
        if not method:
            raise RuntimeError(
                "MCP_INFERENCE_METHOD is not configured. "
                "Make sure AvatarPlugin.bootstrap_inference_runners() is called before "
                "MCPHost is used."
            )
        return method

    def _op(self, op: Any) -> Any:
        return getattr(op, "value", op)

    def _build_config_servers_info(self, servers: dict[str, dict]) -> str:
        lines = []
        for name, cfg in servers.items():
            url = cfg.get("url", "unknown")
            instruction = cfg.get("instruction") or ""
            lines.append(f"- name={name}, url={url}, instruction={instruction}")
        return "MCPHost configured servers:\n" + "\n".join(lines)

    async def _run_mcp_inference(self, *, op: Any, param: dict[str, Any]) -> dict[str, Any]:
        if self.inference_method is None:
            raise RuntimeError(
                "env MCP_INFERENCE_METHOD is not configured. "
                "Set MCP_VDB_TYPE=lancedb and register LanceDBRunner."
            )

        payload = json.dumps(
            {
                "op": self._op(op),
                "param": param,
            },
            ensure_ascii=False,
        ).encode()

        job_ctx = get_job_context()
        raw = await job_ctx.inference_executor.do_inference(self.inference_method, payload)

        if raw is None:
            return {"error": "MCP inference runner returned None"}

        return json.loads(raw.decode())

    async def search_tools(self, *, query: str, ctx: RunContext) -> str:
        logger.info("[MCPHost] search_tools query=%s", query)

        try:
            result = await self._run_mcp_inference(
                op=MCPOp.TOOL_SEARCH,
                param={
                    "query": query,
                    "top_k": 8,
                },
            )
        except Exception as e:
            logger.exception("[MCPHost] search_tools failed")
            return f"MCPHost TOOL_SEARCH failed: {e}"

        if result.get("error"):
            return f"MCPHost TOOL_SEARCH error: {result['error']}"

        tools = result.get("tools", []) or []
        if not tools:
            return f"MCPHost found no tools for query: {query}"

        lines: list[str] = []
        lines.append(f"MCPHost found the following relevant tools for query: {query}")
        lines.append("")
        lines.append(
            "Use the exact Tool ID when calling call_tools. "
            'The call_tools params format is: {"tool_id": {"arg": "value"}}.'
        )
        lines.append("")

        for idx, tool in enumerate(tools, start=1):
            usage = tool.get("usage")
            if usage:
                lines.append(f"### Tool {idx}")
                lines.append(usage)
            else:
                tool_id = tool.get("tool_id", "")
                desc = tool.get("description", "")
                lines.append(f"### Tool {idx}")
                lines.append(f"Tool ID: {tool_id}")
                lines.append(f"When to use: {desc}")

            lines.append("")

        return "\n".join(lines)

    async def call_tools(self, *, params: dict, ctx: RunContext) -> str:
        logger.info("[MCPHost] call_tools count=%d", len(params) if params else 0)

        try:
            result = await self._run_mcp_inference(
                op=MCPOp.TOOL_CALL,
                param={
                    "params": params or {},
                },
            )
        except Exception as e:
            logger.exception("[MCPHost] call_tools failed")
            return f"### MCP TOOL_CALL error\n\n```text\n{e}\n```"

        if result.get("markdown"):
            return result["markdown"]

        if result.get("error"):
            return f"### MCP TOOL_CALL error\n\n```text\n{result['error']}\n```"

        return json.dumps(result, ensure_ascii=False, indent=2)

    async def aclose(self) -> None:
        # Do not disable MCP clients here.
        # The client lifecycle is managed by the runner/worker inference process.
        return
