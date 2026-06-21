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
"""
LanceDB-backed MCP runner lifecycle.

This runner moves MCP server initialization out of per-user Agent sessions and into
the LiveKit worker-level inference runner. The goal is to initialize MCP servers,
MCP client sessions, and the tool registry only once per worker process, then let
all Agent sessions access MCP through LiveKit's inference executor.

Lifecycle:

1. Worker startup
   - LiveKit creates this _InferenceRunner when the runner is registered.
   - initialize() reads MCP_VDB_CONFIG and opens / creates the LanceDB tool table.
   - initialize() reads MCP_SERVERS and submits _initialize_mcp() to a dedicated
     MCP event loop thread.

2. MCP initialization
   - _initialize_mcp() creates one MCPServerRemote per configured server key.
   - Each MCP server is initialized in parallel.
   - Tools are listed from all ready servers.
   - In-memory runtime indexes are built:
       _clients_by_key: server_key -> MCPServerRemote
       _mcp_tools: tool_id -> MCPTool
       _server_info_by_tool_id: tool_id -> server metadata
       _tool_server_key: tool_id -> server_key

3. Tool indexing
   - _sync_tools_to_vdb() compares the current in-memory tool set with LanceDB.
   - Stale tools are deleted.
   - New tools are embedded and inserted.
   - Changed tools are deleted, re-embedded, and reinserted.
   - Unchanged tools are left untouched.

4. Tool search
   - Agent sessions call MCPHost.search_tools().
   - MCPHost forwards TOOL_SEARCH to this runner through inference_executor.
   - _search_tools() embeds the query, searches LanceDB, applies lightweight
     hybrid reranking, filters out tools not present in the live in-memory registry,
     and returns agent-friendly usage hints.

5. Tool invocation
   - Agent sessions call MCPHost.call_tools().
   - MCPHost forwards TOOL_CALL to this runner through inference_executor.
   - _call_tools() submits the async tool calls to the MCP loop thread.
   - _call_tools_async() validates tool IDs and invokes tools concurrently.
   - _call_one() validates arguments against each tool's input schema before calling.

6. Reconnect behavior
   - If a tool call fails with a connection-like error, the runner reconnects only
     the affected MCP server.
   - Reconnect is protected by a per-server asyncio.Lock to avoid duplicate
     concurrent reconnects.
   - After reconnect, in-memory tools for that server are refreshed and the current
     tool call is retried once.
   - LanceDB sync is intentionally skipped during reconnect to avoid blocking the
     MCP event loop; a future refresh_tools operation can handle explicit VDB refresh.

Important design notes:

- Tool IDs should be stable and based on the configured MCP server key, for example:
  "github.search_repositories" instead of relying only on remote serverInfo.name.
- MCP client sessions live in the dedicated MCP loop thread. MCPTool.call() marshals
  calls back to that loop when needed.
- LanceDB is used only for tool retrieval. The live source of truth for invocation is
  always the in-memory _mcp_tools registry.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from typing import Any

from livekit.agents.inference_runner import _InferenceRunner
from livekit.agents.llm.tool_context import ToolError

from alphaavatar.agents.providers import ProviderKind, ProviderTaskConfig
from alphaavatar.agents.providers.embedding import create_embedding_model
from alphaavatar.agents.tools.mcp_api import MCPOp
from alphaavatar.agents.utils.loop_thread import AsyncLoopThread
from alphaavatar.agents.utils.vdb import lancedb

from ..config import DEFAULT_TIMEOUT
from ..log import logger
from ..mcp_server_remote import MCPServerRemote
from ..mcp_tool import MCPTool


class LanceDBRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_mcp_lancedb"

    def __init__(self):
        super().__init__()

        self._servers: dict[str, dict] = {}
        self._clients_by_key: dict[str, MCPServerRemote] = {}
        self._mcp_tools: dict[str, MCPTool] = {}
        self._server_info_by_tool_id: dict[str, dict[str, Any]] = {}

        self._tool_server_key: dict[str, str] = {}
        self._server_reconnect_locks: dict[str, asyncio.Lock] = {}

        self._loop_thread = AsyncLoopThread(name="mcp-loop")
        self._init_future = None
        self._init_error: Exception | None = None
        self._init_lock = threading.Lock()

        self._client = None
        self._tool_table = None
        self._embeddings = None
        self._collection_name: str | None = None

    def _should_reconnect(self, error: Exception) -> bool:
        msg = str(error).lower()

        reconnect_keywords = [
            "connection",
            "connect",
            "closed",
            "broken pipe",
            "timeout",
            "timed out",
            "eof",
            "reset by peer",
            "transport",
            "session",
            "disconnected",
            "network",
        ]

        return any(keyword in msg for keyword in reconnect_keywords)

    def _format_tool_usage(
        self,
        *,
        tool_id: str,
        description: str,
        input_schema: dict[str, Any],
        server_info: dict[str, Any],
    ) -> str:
        properties = input_schema.get("properties", {}) or {}
        required = set(input_schema.get("required", []) or [])

        lines: list[str] = []
        lines.append(f"Tool ID: {tool_id}")
        lines.append(f"When to use: {description or 'No description provided.'}")

        instruction = server_info.get("instruction") if isinstance(server_info, dict) else None
        if instruction:
            lines.append(f"Server instruction: {instruction}")

        lines.append("Arguments:")

        if not properties:
            lines.append("- No arguments required.")
        else:
            for name, schema in properties.items():
                typ = schema.get("type", "any") if isinstance(schema, dict) else "any"
                desc = schema.get("description", "") if isinstance(schema, dict) else ""
                req = "required" if name in required else "optional"
                if desc:
                    lines.append(f"- {name}: {typ}, {req}. {desc}")
                else:
                    lines.append(f"- {name}: {typ}, {req}.")

        example_args = {name: f"<{name}>" for name in properties.keys()}

        lines.append("Call format:")
        lines.append(
            json.dumps(
                {
                    tool_id: example_args,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        return "\n".join(lines)

    def _ensure_collection(self, collection_name: str, embedding_dim: int) -> None:
        if self._client.table_exists(collection_name):
            return

        seed = [
            {
                "id": "__init__",
                "vector": [0.0] * embedding_dim,
                "page_content": "__init__",
                "tool_id": "",
                "server_key": "",
                "server_name": "",
                "tool_name": "",
                "description": "",
                "input_schema_json": "{}",
                "meta_json": "{}",
                "server_info_json": "{}",
                "updated_at": "",
            }
        ]
        table = self._client.create_table(collection_name, seed)
        table.delete("id = '__init__'")

    def _quote_sql(self, value: str) -> str:
        return value.replace("'", "''")

    def _tool_to_row(
        self,
        *,
        tool: MCPTool,
        vector: list[float],
        page_content: str,
        server_info: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": tool.tool_id,
            "vector": vector,
            "page_content": page_content,
            "tool_id": tool.tool_id,
            "server_key": tool.server_key or "",
            "server_name": tool.client_name or "",
            "tool_name": tool.name,
            "description": tool.description_text,
            "input_schema_json": json.dumps(tool.input_schema or {}, ensure_ascii=False),
            "meta_json": json.dumps(tool.meta or {}, ensure_ascii=False),
            "server_info_json": json.dumps(server_info or {}, ensure_ascii=False),
            "updated_at": str(time.time()),
        }

    def _row_to_tool_hint(self, row: dict[str, Any]) -> dict[str, Any]:
        try:
            input_schema = json.loads(row.get("input_schema_json") or "{}")
        except Exception:
            input_schema = {}

        try:
            meta = json.loads(row.get("meta_json") or "{}")
        except Exception:
            meta = {}

        try:
            server_info = json.loads(row.get("server_info_json") or "{}")
        except Exception:
            server_info = {}

        tool_id = str(row.get("tool_id") or row.get("id") or "")
        tool_name = str(row.get("tool_name") or "")
        description = str(row.get("description") or "")

        return {
            "tool_id": tool_id,
            "server_key": row.get("server_key", ""),
            "server_name": row.get("server_name", ""),
            "name": tool_name,
            "description": description,
            "input_schema": input_schema,
            "meta": meta,
            "server_info": server_info,
            "score": row.get("_distance"),
            "usage": self._format_tool_usage(
                tool_id=tool_id,
                description=description,
                input_schema=input_schema,
                server_info=server_info,
            ),
        }

    async def _initialize_mcp(self, servers: dict[str, dict]) -> None:
        self._servers = servers
        self._clients_by_key = {}
        self._mcp_tools = {}
        self._server_info_by_tool_id = {}
        self._tool_server_key = {}

        async def _init_server(
            server_key: str, cfg: dict[str, Any]
        ) -> tuple[str, MCPServerRemote | None]:
            client = MCPServerRemote(server_key=server_key, **cfg)
            try:
                await client.initialize()
                logger.info("[MCPRunner] MCP client ready key=%s url=%s", server_key, client.url)
                return server_key, client
            except Exception:
                logger.exception("[MCPRunner] Failed to initialize MCP client key=%s", server_key)
                try:
                    await client.aclose()
                except Exception:
                    logger.exception(
                        "[MCPRunner] Failed to close failed MCP client key=%s", server_key
                    )
                return server_key, None

        init_results = await asyncio.gather(
            *(_init_server(server_key, cfg) for server_key, cfg in servers.items())
        )

        for server_key, client in init_results:
            if client is not None:
                self._clients_by_key[server_key] = client

        async def _list_tools(
            server_key: str,
            client: MCPServerRemote,
        ) -> tuple[str, MCPServerRemote, list[MCPTool]]:
            try:
                return server_key, client, await client.list_tools()
            except Exception:
                logger.exception(
                    "[MCPRunner] Failed to list tools key=%s url=%s", server_key, client.url
                )
                return server_key, client, []

        listed = await asyncio.gather(
            *(
                _list_tools(server_key, client)
                for server_key, client in self._clients_by_key.items()
            )
        )

        for server_key, server, tools in listed:
            server_info = server.info_dict

            for tool in tools:
                self._mcp_tools[tool.tool_id] = tool
                self._server_info_by_tool_id[tool.tool_id] = server_info
                self._tool_server_key[tool.tool_id] = server_key

        logger.info(
            "[MCPRunner] initialized clients=%d tools=%d",
            len(self._clients_by_key),
            len(self._mcp_tools),
        )

    def _wait_initialized(self) -> None:
        with self._init_lock:
            if self._init_error is not None:
                raise RuntimeError(f"MCP runner initialization failed: {self._init_error}")

            future = self._init_future
            if future is None:
                return

            try:
                future.result(timeout=DEFAULT_TIMEOUT)
                self._init_future = None
            except Exception as e:
                self._init_error = e
                logger.exception("[MCPRunner] initialization failed")
                raise

    def _sync_tools_to_vdb(self) -> dict[str, Any]:
        result = {
            "inserted": 0,
            "updated": 0,
            "written": 0,
            "unchanged": 0,
            "deleted_ids": [],
            "error": None,
        }

        try:
            current_tools = self._mcp_tools or {}
            current_ids = set(current_tools.keys())

            existing_rows = []
            try:
                existing_rows = self._tool_table.to_list()
            except Exception:
                existing_rows = []

            existing_by_id: dict[str, dict[str, Any]] = {}
            for row in existing_rows:
                tool_id = str(row.get("tool_id") or row.get("id") or "")
                if tool_id:
                    existing_by_id[tool_id] = row

            existing_ids = set(existing_by_id.keys())

            stale_ids = sorted(existing_ids - current_ids)
            if stale_ids:
                quoted_ids = ",".join(f"'{self._quote_sql(x)}'" for x in stale_ids)
                self._tool_table.delete(f"id IN ({quoted_ids})")
                result["deleted_ids"].extend(stale_ids)

            texts_to_embed: list[str] = []
            tools_to_write: list[MCPTool] = []
            page_content_by_tool_id: dict[str, str] = {}

            for tool_id, tool in current_tools.items():
                server_info = self._server_info_by_tool_id.get(tool_id, {})
                page_content = tool.to_vdb_text(server_info=server_info)
                page_content_by_tool_id[tool_id] = page_content

                existing = existing_by_id.get(tool_id)

                if existing is None:
                    texts_to_embed.append(page_content)
                    tools_to_write.append(tool)
                    continue

                old_page_content = existing.get("page_content", "")
                if old_page_content != page_content:
                    texts_to_embed.append(page_content)
                    tools_to_write.append(tool)
                    continue

                result["unchanged"] += 1

            update_ids = [tool.tool_id for tool in tools_to_write if tool.tool_id in existing_ids]
            if update_ids:
                quoted_ids = ",".join(f"'{self._quote_sql(x)}'" for x in update_ids)
                self._tool_table.delete(f"id IN ({quoted_ids})")
                result["deleted_ids"].extend(update_ids)

            if tools_to_write:
                vectors = self._embeddings.embed_documents(texts_to_embed)

                rows_to_add = [
                    self._tool_to_row(
                        tool=tool,
                        vector=vector,
                        page_content=page_content_by_tool_id[tool.tool_id],
                        server_info=self._server_info_by_tool_id.get(tool.tool_id, {}),
                    )
                    for tool, vector in zip(tools_to_write, vectors, strict=True)
                ]

                self._tool_table.add(rows_to_add)

                result["inserted"] = sum(
                    1 for tool in tools_to_write if tool.tool_id not in existing_ids
                )
                result["updated"] = len(update_ids)
                result["written"] = len(rows_to_add)

            logger.info(
                "[MCPRunner] synced tools to LanceDB written=%d inserted=%d updated=%d unchanged=%d deleted=%d",
                result["written"],
                result["inserted"],
                result["updated"],
                result["unchanged"],
                len(result["deleted_ids"]),
            )

        except Exception as e:
            result["error"] = str(e)
            logger.exception("[MCPRunner] failed to sync tools to LanceDB")

        return result

    def _rerank_tool_rows(self, *, query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        q = (query or "").lower()
        tokens = [t for t in re.split(r"[\s,.;:/\\|]+", q) if t]

        def rank_key(row: dict[str, Any]) -> float:
            distance = float(row.get("_distance", 999.0) or 999.0)

            tool_id = str(row.get("tool_id", "")).lower()
            tool_name = str(row.get("tool_name", "")).lower()
            server_key = str(row.get("server_key", "")).lower()
            server_name = str(row.get("server_name", "")).lower()
            desc = str(row.get("description", "")).lower()

            bonus = 0.0

            if tool_id and tool_id in q:
                bonus += 4.0
            if tool_name and tool_name in q:
                bonus += 3.0
            if server_key and server_key in q:
                bonus += 2.0
            if server_name and server_name in q:
                bonus += 1.5

            for token in tokens:
                if not token:
                    continue

                if token in tool_id:
                    bonus += 0.7
                elif token in tool_name:
                    bonus += 0.5
                elif token in server_key:
                    bonus += 0.4
                elif token in desc:
                    bonus += 0.2

            # LanceDB distance 越小越好，所以 distance - bonus。
            return distance - bonus

        return sorted(rows, key=rank_key)

    def _search_tools(self, *, query: str, top_k: int = 8) -> dict[str, Any]:
        out = {
            "tools": [],
            "error": None,
        }

        try:
            self._wait_initialized()

            if not query:
                query = "available MCP tools"

            query_vec = self._embeddings.embed_query(query)
            all_count = self._tool_table.count_rows()
            if all_count == 0:
                return out

            fetch_k = min(max(top_k * 6, 32), all_count)
            rows = self._tool_table.search(query_vec).limit(fetch_k).to_list()
            rows = self._rerank_tool_rows(query=query, rows=rows)

            seen: set[str] = set()
            tools: list[dict[str, Any]] = []

            for row in rows:
                hint = self._row_to_tool_hint(row)
                tool_id = hint["tool_id"]

                if not tool_id or tool_id in seen:
                    continue

                if tool_id not in self._mcp_tools:
                    continue

                seen.add(tool_id)
                tools.append(hint)

                if len(tools) >= top_k:
                    break

            out["tools"] = tools

        except Exception as e:
            out["error"] = str(e)
            logger.exception("[MCPRunner] search_tools failed")

        return out

    def _validate_tool_args(self, *, tool: MCPTool, args: dict[str, Any]) -> list[str]:
        schema = tool.input_schema or {}
        errors: list[str] = []

        required = schema.get("required", []) or []
        properties = schema.get("properties", {}) or {}
        additional_properties = schema.get("additionalProperties", True)

        for key in required:
            if key not in args:
                errors.append(f"Missing required argument: {key}")

        if additional_properties is False:
            for key in args:
                if key not in properties:
                    errors.append(f"Unexpected argument: {key}")

        for key, value in args.items():
            prop = properties.get(key)
            if not isinstance(prop, dict):
                continue

            expected_type = prop.get("type")
            if not expected_type:
                continue

            if not self._json_type_matches(value, expected_type):
                errors.append(
                    f"Invalid type for argument '{key}': expected {expected_type}, got {type(value).__name__}"
                )

        return errors

    def _json_type_matches(self, value: Any, expected_type: Any) -> bool:
        if isinstance(expected_type, list):
            return any(self._json_type_matches(value, t) for t in expected_type)

        match expected_type:
            case "string":
                return isinstance(value, str)
            case "number":
                return isinstance(value, int | float) and not isinstance(value, bool)
            case "integer":
                return isinstance(value, int) and not isinstance(value, bool)
            case "boolean":
                return isinstance(value, bool)
            case "object":
                return isinstance(value, dict)
            case "array":
                return isinstance(value, list)
            case "null":
                return value is None
            case _:
                return True

    async def _reconnect_server_for_tool(self, tool_id: str) -> bool:
        server_key = self._tool_server_key.get(tool_id)
        if not server_key:
            logger.warning("[MCPRunner] no server_key found for tool=%s", tool_id)
            return False

        return await self._reinitialize_server(server_key)

    async def _reinitialize_server(self, server_key: str) -> bool:
        lock = self._server_reconnect_locks.setdefault(server_key, asyncio.Lock())

        async with lock:
            return await self._reinitialize_server_locked(server_key)

    async def _reinitialize_server_locked(self, server_key: str) -> bool:
        cfg = self._servers.get(server_key)
        if not cfg:
            logger.warning("[MCPRunner] missing server config for server_key=%s", server_key)
            return False

        logger.info("[MCPRunner] reinitializing MCP server key=%s", server_key)

        old_client = self._clients_by_key.get(server_key)
        if old_client is not None:
            try:
                await old_client.aclose()
            except Exception:
                logger.exception("[MCPRunner] failed to close old MCP server key=%s", server_key)

        try:
            new_client = MCPServerRemote(
                server_key=server_key,
                **cfg,
            )
            await new_client.initialize()
            tools = await new_client.list_tools()

            old_tool_ids = [tid for tid, key in self._tool_server_key.items() if key == server_key]

            for tid in old_tool_ids:
                self._mcp_tools.pop(tid, None)
                self._server_info_by_tool_id.pop(tid, None)
                self._tool_server_key.pop(tid, None)

            server_info = new_client.info_dict
            for tool in tools:
                self._mcp_tools[tool.tool_id] = tool
                self._server_info_by_tool_id[tool.tool_id] = server_info
                self._tool_server_key[tool.tool_id] = server_key

            self._clients_by_key[server_key] = new_client

            logger.info(
                "[MCPRunner] reinitialized MCP server key=%s tools=%d",
                server_key,
                len(tools),
            )
            logger.info(
                "[MCPRunner] skipped VDB sync during reconnect key=%s; tools are refreshed in memory",
                server_key,
            )

            return True

        except Exception:
            logger.exception("[MCPRunner] failed to reinitialize server key=%s", server_key)
            return False

    async def _call_one(self, tool_id: str, raw_args: Any) -> Any:
        if tool_id not in self._mcp_tools:
            raise ToolError(f"MCP tool not found: {tool_id}")

        if raw_args is None:
            raw_args = {}

        if not isinstance(raw_args, dict):
            raise ToolError(f"Invalid params for tool '{tool_id}': expected dict")

        tool = self._mcp_tools[tool_id]

        validation_errors = self._validate_tool_args(tool=tool, args=raw_args)
        if validation_errors:
            usage = self._format_tool_usage(
                tool_id=tool.tool_id,
                description=tool.description_text,
                input_schema=tool.input_schema,
                server_info=self._server_info_by_tool_id.get(tool.tool_id, {}),
            )
            raise ToolError(
                "Invalid MCP tool arguments:\n"
                + "\n".join(f"- {e}" for e in validation_errors)
                + "\n\nCorrect usage:\n"
                + usage
            )

        try:
            return await tool.call(raw_args)
        except Exception as first_error:
            if not self._should_reconnect(first_error):
                raise

            logger.warning(
                "[MCPRunner] tool=%s failed with connection-like error, attempting server reconnect: %s",
                tool_id,
                first_error,
            )

            reconnected = await self._reconnect_server_for_tool(tool_id)
            if not reconnected:
                raise

            refreshed_tool = self._mcp_tools.get(tool_id)
            if refreshed_tool is None:
                raise ToolError(
                    f"Tool {tool_id} disappeared after reconnect. Original error: {first_error}"
                )

            return await refreshed_tool.call(raw_args)

    async def _call_tools_async(self, *, params: dict[str, Any]) -> dict[str, Any]:
        call_start = time.perf_counter()

        if not params:
            return {
                "markdown": "MCPHost TOOL_CALL received empty params",
                "results": [],
                "error": None,
            }

        ordered_items: list[tuple[str, Any]] = list(params.items())
        missing = [tool_id for tool_id, _ in ordered_items if tool_id not in self._mcp_tools]

        if missing:
            available_hint = sorted(self._mcp_tools.keys())[:50]
            return {
                "markdown": (
                    "### MCP TOOL_CALL error\n"
                    "Some tools are not available in this MCPHost.\n\n"
                    "**Missing tools:**\n" + "\n".join(f"- {x}" for x in missing) + "\n\n"
                    "**Available tools (partial):**\n" + "\n".join(f"- {x}" for x in available_hint)
                ),
                "results": [],
                "error": "missing tools",
            }

        async def _safe_call(tool_id: str, raw_args: Any) -> dict[str, Any]:
            tool_start = time.perf_counter()
            try:
                result = await self._call_one(tool_id, raw_args)
                return {
                    "tool_id": tool_id,
                    "args": raw_args or {},
                    "ok": True,
                    "result": result,
                    "elapsed": time.perf_counter() - tool_start,
                    "error": None,
                }
            except Exception as e:
                logger.exception("[MCPRunner] tool=%s failed", tool_id)
                return {
                    "tool_id": tool_id,
                    "args": raw_args or {},
                    "ok": False,
                    "result": None,
                    "elapsed": time.perf_counter() - tool_start,
                    "error": str(e),
                }

        results = await asyncio.gather(
            *(_safe_call(tool_id, raw_args) for tool_id, raw_args in ordered_items)
        )

        lines: list[str] = []
        lines.append("### MCP TOOL_CALL results")
        lines.append("")
        lines.append(f"- Total tools requested: **{len(ordered_items)}**")
        lines.append("")

        for item in results:
            lines.append(f"#### {item['tool_id']}")
            lines.append("")
            lines.append("**Args:**")
            lines.append("```json")
            lines.append(json.dumps(item["args"], ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

            if not item["ok"]:
                lines.append("**Status:** ❌ Error")
                lines.append("")
                lines.append("```text")
                lines.append(item["error"] or "unknown error")
                lines.append("```")
            else:
                lines.append("**Status:** ✅ OK")
                lines.append("")
                lines.append("```text")
                result = item["result"]
                lines.append(
                    result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                )
                lines.append("```")

            lines.append("")

        logger.info(
            "[MCPRunner] call_tools finished elapsed=%.2fs success=%d error=%d",
            time.perf_counter() - call_start,
            sum(1 for r in results if r["ok"]),
            sum(1 for r in results if not r["ok"]),
        )

        return {
            "markdown": "\n".join(lines),
            "results": results,
            "error": None,
        }

    def _call_tools(self, *, params: dict[str, Any]) -> dict[str, Any]:
        try:
            self._wait_initialized()
            fut = self._loop_thread.submit_future(self._call_tools_async(params=params))
            return fut.result(timeout=DEFAULT_TIMEOUT)
        except Exception as e:
            logger.exception("[MCPRunner] call_tools failed")
            return {
                "markdown": f"### MCP TOOL_CALL error\n\n```text\n{e}\n```",
                "results": [],
                "error": str(e),
            }

    #
    # Runner Interface
    #

    def _get_vdb_config(self, config: dict[str, Any]) -> dict[str, Any]:
        vdb_config = dict(config)
        vdb_config.pop("embedding", None)
        return vdb_config

    def _get_mcp_embeddings(self, config: dict[str, Any]):
        embedding_config = config.get("embedding")

        if not embedding_config:
            raise ValueError("`embedding` is required in MCP_VDB_CONFIG")

        provider = embedding_config.get("provider")
        model = embedding_config.get("model")
        extra = embedding_config.get("extra") or {}

        if not provider:
            raise ValueError("`embedding.provider` is required in MCP_VDB_CONFIG")
        if not model:
            raise ValueError("`embedding.model` is required in MCP_VDB_CONFIG")

        task_config = ProviderTaskConfig(
            kind=ProviderKind.EMBEDDING,
            provider=provider,
            model=model,
            extra=extra,
        )

        return create_embedding_model(task_config)

    def initialize(self) -> None:
        config = os.getenv("MCP_VDB_CONFIG", "{}")
        config = json.loads(config)

        self._collection_name = config.get("collection_name")
        if not self._collection_name:
            raise ValueError("collection_name is required in MCP_VDB_CONFIG")

        self._client = lancedb.get_client(**self._get_vdb_config(config))

        self._embeddings = self._get_mcp_embeddings(config)
        embedding_dim = len(self._embeddings.embed_query("dimension-probe"))

        self._ensure_collection(self._collection_name, embedding_dim)
        self._tool_table = self._client.open_table(self._collection_name)

        servers = os.getenv("MCP_SERVERS", "{}")
        servers = json.loads(servers)

        self._init_future = self._loop_thread.submit_future(self._initialize_mcp(servers))

        self._wait_initialized()
        self._sync_tools_to_vdb()

    def run(self, data: bytes) -> bytes | None:
        json_data = json.loads(data)
        match json_data["op"]:
            case MCPOp.TOOL_SEARCH:
                result = self._search_tools(**json_data["param"])
                return json.dumps(result, ensure_ascii=False).encode()
            case MCPOp.TOOL_CALL:
                result = self._call_tools(**json_data["param"])
                return json.dumps(result, ensure_ascii=False).encode()
            case _:
                return None
