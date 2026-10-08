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
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from alphaavatar.agents.avatar.provider.schemas import ModelTextPart
from alphaavatar.agents.runtime.capability.result import CapabilityResult
from alphaavatar.agents.tools.schemas import ToolError

from .enums import MCPOp, MCPOutputMode
from .log import redact_url

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime


class MCPHost:
    def __init__(self, *, runtime: AvatarRuntime, servers: dict[str, dict[str, Any]]) -> None:
        self._runtime = runtime
        self._servers = deepcopy(servers)

    @property
    def servers_info(self) -> str:
        return "\n".join(
            f"- name={name}, url={redact_url(config.get('url', 'unknown'))}, "
            f"instruction={config.get('instruction') or ''}"
            for name, config in self._servers.items()
        )

    def _validate_servers(self, keys: list[str] | None) -> None:
        if keys is not None and (unknown := set(keys) - self._servers.keys()):
            raise ToolError(f"Unknown MCP server keys: {', '.join(sorted(unknown))}")

    async def _run(self, op: MCPOp, params: dict[str, Any]) -> dict[str, Any]:
        method = os.getenv("MCP_VDB_INFERENCE_METHOD")
        if not method:
            raise ToolError("MCP inference runner is not configured")
        payload = json.dumps({"op": op.value, "param": params}, ensure_ascii=False).encode()
        raw = await self._runtime.inference.do_inference(method, payload)
        if raw is None:
            raise ToolError("MCP inference runner returned no response")
        result = json.loads(raw.decode())
        if not isinstance(result, dict):
            raise ToolError("MCP inference runner returned an invalid response")
        if result.get("error"):
            # Do not promote service errors to successful text or expose credentials in errors.
            raise ToolError(f"MCP {op.value} failed; consult the worker diagnostic log")
        return result

    async def search_tools(
        self,
        *,
        query: str,
        top_k: int = 8,
        server_keys: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> str:
        self._validate_servers(server_keys)
        result = await self._run(
            MCPOp.TOOL_SEARCH,
            {"query": query, "top_k": top_k, "server_keys": server_keys, "categories": categories},
        )
        tools = result.get("tools") or []
        if not tools:
            return f"MCPHost found no tools for query: {query}"
        lines = [
            f"MCPHost found the following relevant tools for query: {query}",
            "",
            'Use exact Tool IDs in params_json: {"tool_id": {"arg": "value"}}.',
            "",
        ]
        for index, tool in enumerate(tools, start=1):
            lines.append(f"### Tool {index}")
            lines.append(
                tool.get("usage")
                or (
                    f"Tool ID: {tool.get('tool_id', '')}\n"
                    f"When to use: {tool.get('description', '')}"
                )
            )
            lines.append("")
        return "\n".join(lines)

    async def refresh_tools(self, *, server_keys: list[str] | None = None) -> CapabilityResult:
        self._validate_servers(server_keys)
        result = await self._run(MCPOp.REFRESH_TOOLS, {"server_keys": server_keys})
        servers = result.get("servers")
        expected = set(self._servers if server_keys is None else server_keys)
        valid = isinstance(servers, dict) and bool(expected) and set(servers) == expected
        failed = not valid
        lines = ["MCPHost refresh results:", ""]

        if not valid:
            lines.append("Refresh results are incomplete or invalid; success is not confirmed.")

        for key in sorted(expected):
            info = servers.get(key) if isinstance(servers, dict) else None
            if not isinstance(info, dict) or "error" not in info:
                lines.append(f"- {key}: UNKNOWN; no valid refresh result was returned.")
                failed = True
                continue
            if info["error"] is not None:
                lines.append(f"- {key}: FAILED; consult the worker diagnostics.")
                failed = True
                continue
            changes = [info.get(label) for label in ("added", "removed", "updated")]
            if (
                type(info.get("total")) is not int
                or info["total"] < 0
                or any(not isinstance(v, list) for v in changes)
            ):
                lines.append(f"- {key}: UNKNOWN; malformed refresh summary.")
                failed = True
                continue
            lines.append(
                f"- {key}: {info['total']} tools (added {len(changes[0])}, "
                f"removed {len(changes[1])}, updated {len(changes[2])})"
            )
            for label, values in zip(("added", "removed", "updated"), changes, strict=True):
                lines.extend(f"    {label}: {identity}" for identity in values)
        return CapabilityResult(parts=(ModelTextPart("\n".join(lines)),), is_error=failed)

    async def call_tools(
        self,
        *,
        params: dict[str, dict[str, Any]],
        output_mode: MCPOutputMode = MCPOutputMode.RAW,
    ) -> CapabilityResult:
        if not params:
            raise ToolError("MCP tool_call requires at least one tool")

        result = await self._run(
            MCPOp.TOOL_CALL, {"params": params, "output_mode": output_mode.value}
        )
        rows = result.get("results")
        valid = (
            isinstance(rows, list)
            and len(rows) == len(params)
            and all(
                isinstance(row, dict)
                and isinstance(row.get("tool_id"), str)
                and type(row.get("ok")) is bool
                for row in rows
            )
            and {row["tool_id"] for row in rows} == set(params)
        )

        failed = not valid or any(not row["ok"] or row.get("error") for row in rows)
        text = result.get("markdown")
        if not isinstance(text, str) or not text.strip():
            text = json.dumps(result, ensure_ascii=False, indent=2)

        if failed:
            text += (
                "\n\nNot all requested operations have confirmed successful results. "
                "An error does not prove that a remote action was rolled back. "
                "Do not repeat state-changing operations without checking their actual state."
            )

        return CapabilityResult(parts=(ModelTextPart(text),), is_error=bool(failed))

    async def aclose(self) -> None:
        # Remote clients and the VDB are owned by the inference worker, not this session facade.
        return
