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

import asyncio
import json
import os
import re
import time
from collections.abc import Coroutine
from typing import Any

from alphaavatar.agents.avatar.provider.enums import ProviderKind
from alphaavatar.agents.avatar.provider.factory import create_embedding_model
from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig
from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.runtime.plugin import AvatarModule
from alphaavatar.agents.tools.schemas import ToolError
from alphaavatar.agents.utils.files.work_dirs import WorkspacePaths
from alphaavatar.agents.utils.loop_thread import AsyncLoopThread
from alphaavatar.agents.utils.vdb import lancedb
from alphaavatar.core.cleanup import wait_for_cleanup

from ..config import DEFAULT_TIMEOUT, MCPServerConfig
from ..enums import MCPOp, MCPOutputMode
from ..log import logger
from ..mcp_server_remote import MCPServerRemote
from ..mcp_tool import MCPTool
from ..schemas import MCP_TOOL_CATEGORIES, MCP_TOP_K_RANGE

COMPACT_RESULT_MAX_CHARS = 2000
MAX_TOOL_CALLS = 64


class LanceDBRunner(InferenceRunner):
    """Serial database work stays in this process; remote sessions own one async loop."""

    INFERENCE_METHOD = "alphaavatar.mcp.vdb.lancedb"

    def __init__(self) -> None:
        self._servers: dict[str, dict[str, Any]] = {}
        self._clients_by_key: dict[str, MCPServerRemote] = {}
        self._owned_clients: dict[MCPServerRemote, str] = {}
        self._mcp_tools: dict[str, MCPTool] = {}
        self._server_info_by_tool_id: dict[str, dict[str, Any]] = {}
        self._tool_server_key: dict[str, str] = {}
        self._listed_servers: set[str] = set()
        self._loop_thread: AsyncLoopThread | None = None
        self._client = self._tool_table = self._embeddings = None
        self._collection_name: str | None = None
        self._initialized = self._closed = False
        self._close_error: Exception | None = None

    @staticmethod
    def _quote_sql(value: str) -> str:
        return value.replace("'", "''")

    @staticmethod
    def _format_tool_usage(*, tool_id, description, input_schema, server_info) -> str:
        properties = input_schema.get("properties") or {}
        required = set(input_schema.get("required") or [])
        lines = [f"Tool ID: {tool_id}", f"When to use: {description or 'No description provided.'}"]
        if instruction := server_info.get("instruction"):
            lines.append(f"Server instruction: {instruction}")
        lines.append("Arguments:")
        for name, schema in properties.items():
            schema = schema if isinstance(schema, dict) else {}
            kind, detail = schema.get("type", "any"), schema.get("description", "")
            requirement = "required" if name in required else "optional"
            lines.append(f"- {name}: {kind}, {requirement}. {detail}".rstrip())
        if not properties:
            lines.append("- No arguments required.")
        example = {tool_id: {key: f"<{key}>" for key in properties}}
        lines.extend(("Call format:", json.dumps(example, ensure_ascii=False, indent=2)))
        return "\n".join(lines)

    def _submit(self, operation: Coroutine[Any, Any, Any], *, timeout: float | None = None):
        if self._loop_thread is None:
            operation.close()
            raise RuntimeError("MCP loop is not initialized")
        # Deadline ownership is inside the async operation, so cleanup settles before reuse.
        return self._loop_thread.submit(operation, timeout=timeout)

    async def _release_client(self, client: MCPServerRemote) -> None:
        await client.aclose()
        self._owned_clients.pop(client, None)

    def _replace_tools(self, key: str, client: MCPServerRemote, tools: list[MCPTool]) -> None:
        replacements = {tool.tool_id: tool for tool in tools}
        if len(replacements) != len(tools):
            raise ValueError("MCP server returned duplicate tool identities")
        for identity in replacements:
            if identity in self._tool_server_key and self._tool_server_key[identity] != key:
                raise ValueError("MCP tool identity collides with another server")
        for identity in [item for item, owner in self._tool_server_key.items() if owner == key]:
            self._mcp_tools.pop(identity, None)
            self._server_info_by_tool_id.pop(identity, None)
            self._tool_server_key.pop(identity, None)
        for identity, tool in replacements.items():
            self._mcp_tools[identity] = tool
            self._server_info_by_tool_id[identity] = client.info_dict
            self._tool_server_key[identity] = key
        self._listed_servers.add(key)

    async def _connect_server(self, key: str) -> None:
        if key in self._owned_clients.values():
            raise RuntimeError("Previous MCP client cleanup must finish before reconnecting")
        client = MCPServerRemote(server_key=key, **self._servers[key])
        self._owned_clients[client] = key
        try:
            await client.initialize()
            tools = await client.list_tools()
            self._replace_tools(key, client, tools)
        except BaseException as original:
            try:
                await self._release_client(client)
            except BaseException as cleanup:
                raise original from cleanup
            raise
        self._clients_by_key[key] = client

    async def _initialize_mcp(self) -> None:
        async def connect(key: str) -> None:
            try:
                await self._connect_server(key)
            except Exception as error:
                logger.warning(
                    "MCP discovery unavailable server=%s error_type=%s", key, type(error).__name__
                )

        async with asyncio.TaskGroup() as group:
            for key in self._servers:
                group.create_task(connect(key), name=f"mcp_connect:{key}")

    def _ensure_collection(self, name: str, dimension: int) -> None:
        if not self._client.table_exists(name):
            seed = {
                "id": "__init__",
                "vector": [0.0] * dimension,
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
            table = self._client.create_table(name, [seed])
            table.delete("id = '__init__'")
        self._tool_table = self._client.open_table(name)

    def _tool_to_row(self, tool: MCPTool, vector: list[float], text: str) -> dict[str, Any]:
        return {
            "id": tool.tool_id,
            "vector": vector,
            "page_content": text,
            "tool_id": tool.tool_id,
            "server_key": tool.server_key or "",
            "server_name": tool.client_name or "",
            "tool_name": tool.name,
            "description": tool.description_text,
            "input_schema_json": json.dumps(tool.input_schema, ensure_ascii=False),
            "meta_json": json.dumps(tool.meta or {}, ensure_ascii=False),
            "server_info_json": json.dumps(
                self._server_info_by_tool_id.get(tool.tool_id, {}), ensure_ascii=False
            ),
            "updated_at": str(time.time()),
        }

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
            stored = self._tool_table.to_arrow().select(["id", "page_content", "server_key"])
            existing = {str(row["id"]): row for row in stored.to_pylist()}
            changed, texts = [], []
            for identity, tool in self._mcp_tools.items():
                text = tool.to_vdb_text(server_info=self._server_info_by_tool_id.get(identity, {}))
                if identity in existing and existing[identity].get("page_content") == text:
                    result["unchanged"] += 1
                    continue
                changed.append(tool)
                texts.append(text)
            # Compute replacements first. An embedding failure must not delete stored rows.
            if changed:
                vectors = self._embeddings.embed_documents(texts)
                rows = [
                    self._tool_to_row(tool, vector, text)
                    for tool, vector, text in zip(changed, vectors, texts, strict=True)
                ]
                merge = self._tool_table.merge_insert("id")
                merge.when_matched_update_all().when_not_matched_insert_all().execute(rows)
                result["inserted"] = sum(tool.tool_id not in existing for tool in changed)
                result["updated"] = len(changed) - result["inserted"]
                result["written"] = len(changed)
            stale = sorted(
                identity
                for identity, row in existing.items()
                if identity not in self._mcp_tools and row.get("server_key") in self._listed_servers
            )
            if stale:
                quoted = ",".join(f"'{self._quote_sql(identity)}'" for identity in stale)
                self._tool_table.delete(f"id IN ({quoted})")
                result["deleted_ids"] = stale
        except Exception as error:
            result["error"] = f"MCP index update failed ({type(error).__name__})"
            logger.warning("MCP index update failed error_type=%s", type(error).__name__)
        return result

    def _row_to_tool_hint(self, row: dict[str, Any]) -> dict[str, Any]:
        identity = str(row.get("tool_id") or row.get("id") or "")
        tool = self._mcp_tools[identity]
        info = self._server_info_by_tool_id.get(identity, {})
        return {
            "tool_id": identity,
            "server_key": tool.server_key,
            "server_name": tool.client_name,
            "name": tool.name,
            "description": tool.description_text,
            "input_schema": tool.input_schema,
            "meta": tool.meta or {},
            "server_info": info,
            "score": row.get("_distance"),
            "usage": self._format_tool_usage(
                tool_id=identity,
                description=tool.description_text,
                input_schema=tool.input_schema,
                server_info=info,
            ),
        }

    @staticmethod
    def _rerank_tool_rows(*, query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query = query.lower()
        tokens = [token for token in re.split(r"[\s,.;:/\\|]+", query) if token]

        def rank(row):
            distance = row.get("_distance")
            score = float(distance) if distance is not None else 999.0
            fields = [
                str(row.get(key) or "").lower()
                for key in ("tool_id", "tool_name", "server_key", "server_name", "description")
            ]
            for value, weight in zip(fields[:4], (4.0, 3.0, 2.0, 1.5), strict=True):
                if value and value in query:
                    score -= weight
            for token in tokens:
                for value, weight in zip(
                    (fields[0], fields[1], fields[2], fields[4]), (0.7, 0.5, 0.4, 0.2), strict=True
                ):
                    if token in value:
                        score -= weight
                        break
            return score

        return sorted(rows, key=rank)

    def _validate_keys(self, keys: list[str] | None) -> list[str]:
        if keys is None:
            return list(self._servers)
        if (
            not isinstance(keys, list)
            or not keys
            or any(not isinstance(key, str) or not key for key in keys)
        ):
            raise ValueError("server_keys must be a nonempty list of names")
        if set(keys) - self._servers.keys():
            raise ValueError("server_keys contains an unconfigured MCP server")
        return sorted(set(keys))

    def _search_tools(
        self, *, query: str, top_k: int = 8, server_keys=None, categories=None
    ) -> dict[str, Any]:
        try:
            low, high = MCP_TOP_K_RANGE
            if type(top_k) is not int or not low <= top_k <= high:
                raise ValueError("top_k is outside the supported range")
            keys = set(self._validate_keys(server_keys))
            if categories is not None and (
                not isinstance(categories, list)
                or not categories
                or any(category not in MCP_TOOL_CATEGORIES for category in categories)
            ):
                raise ValueError("Unsupported MCP tool categories")
            if not isinstance(query, str):
                raise ValueError("MCP query must be text")
            eligible = {
                identity
                for identity, tool in self._mcp_tools.items()
                if tool.server_key in keys and (categories is None or tool.category in categories)
            }
            if not eligible:
                return {"tools": [], "error": None}
            query = query or "available MCP tools"
            vector = self._embeddings.embed_query(query)
            quoted = ",".join(f"'{self._quote_sql(identity)}'" for identity in sorted(eligible))
            search = self._tool_table.search(vector).where(f"tool_id IN ({quoted})", prefilter=True)
            rows = search.limit(min(max(top_k * 6, 32), len(eligible))).to_list()
            rows = self._rerank_tool_rows(query=query, rows=rows)
            seen, tools = set(), []
            for row in rows:
                identity = str(row.get("tool_id") or row.get("id") or "")
                if identity not in eligible or identity in seen:
                    continue
                seen.add(identity)
                tools.append(self._row_to_tool_hint(row))
                if len(tools) == top_k:
                    break
            return {"tools": tools, "error": None}
        except Exception as error:
            return {"tools": [], "error": f"MCP discovery failed ({type(error).__name__})"}

    @classmethod
    def _json_type_matches(cls, value: Any, expected: Any) -> bool:
        if isinstance(expected, list):
            return any(cls._json_type_matches(value, item) for item in expected)
        match expected:
            case "string":
                return isinstance(value, str)
            case "number":
                return isinstance(value, int | float) and not isinstance(value, bool)
            case "integer":
                return type(value) is int
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

    def _validate_tool_args(self, *, tool: MCPTool, args: dict[str, Any]) -> list[str]:
        schema, errors = tool.input_schema, []
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in args:
                errors.append(f"Missing required argument: {key}")
        for key, value in args.items():
            if key not in properties and schema.get("additionalProperties") is False:
                errors.append(f"Unexpected argument: {key}")
            prop = properties.get(key)
            if (
                isinstance(prop, dict)
                and prop.get("type")
                and not self._json_type_matches(value, prop["type"])
            ):
                errors.append(f"Invalid type for argument: {key}")
        return errors

    async def _call_one(self, identity: str, arguments: Any) -> Any:
        if identity not in self._mcp_tools:
            raise ToolError(f"MCP tool not found: {identity}")
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            raise ToolError("MCP tool arguments must be an object")
        tool = self._mcp_tools[identity]
        if errors := self._validate_tool_args(tool=tool, args=arguments):
            raise ToolError("Invalid MCP tool arguments: " + "; ".join(errors))
        # A transport failure after dispatch does not establish whether a remote write committed.
        return await tool.call(arguments)

    async def _call_tools_async(
        self, *, params: dict[str, Any], output_mode: str
    ) -> dict[str, Any]:
        async def call(identity, arguments):
            started = time.perf_counter()
            try:
                value = await self._call_one(identity, arguments)
                return {
                    "tool_id": identity,
                    "args": arguments or {},
                    "ok": True,
                    "result": value,
                    "error": None,
                    "elapsed": time.perf_counter() - started,
                }
            except Exception as error:
                message = (
                    str(error)
                    if isinstance(error, ToolError)
                    else "MCP response is unconfirmed; do not automatically retry"
                )
                logger.warning(
                    "MCP call failed tool_id=%s error_type=%s", identity, type(error).__name__
                )
                return {
                    "tool_id": identity,
                    "args": arguments or {},
                    "ok": False,
                    "result": None,
                    "error": message,
                    "elapsed": time.perf_counter() - started,
                }

        tasks = [
            asyncio.create_task(call(identity, arguments), name="mcp_tool_call")
            for identity, arguments in params.items()
        ]
        try:
            results = await asyncio.gather(*tasks)
        except BaseException:

            async def settle():
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

            await wait_for_cleanup(asyncio.create_task(settle(), name="mcp_batch_cleanup"))
            raise
        compact = output_mode == MCPOutputMode.COMPACT
        lines = ["### MCP TOOL_CALL results", "", f"- Total tools requested: **{len(params)}**", ""]
        for row in results:
            lines.extend((f"#### {row['tool_id']}", ""))
            if not compact:
                arguments = json.dumps(row["args"], ensure_ascii=False, indent=2)
                lines.extend(("**Args:**", "```json", arguments, "```", ""))
            lines.extend(("**Status:** OK" if row["ok"] else "**Status:** Error", "", "```text"))
            value = row["result"] if row["ok"] else row["error"]
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if compact and len(text) > COMPACT_RESULT_MAX_CHARS:
                omitted = len(text) - COMPACT_RESULT_MAX_CHARS
                text = text[:COMPACT_RESULT_MAX_CHARS] + f"\n[Truncated {omitted} characters]"
            lines.extend((text, "```", ""))
            if compact:
                row.pop("args", None)
                if row["ok"]:
                    row["result"] = text
        return {"markdown": "\n".join(lines), "results": results, "error": None}

    def _call_tools(
        self, *, params: dict[str, Any], output_mode: str = MCPOutputMode.RAW
    ) -> dict[str, Any]:
        try:
            if not isinstance(params, dict) or not 1 <= len(params) <= MAX_TOOL_CALLS:
                raise ValueError("MCP tool batch is empty or exceeds capacity")
            if any(not isinstance(identity, str) for identity in params):
                raise ValueError("MCP tool identities must be strings")
            if output_mode not in (MCPOutputMode.RAW, MCPOutputMode.COMPACT):
                raise ValueError("Unsupported MCP output mode")
            if set(params) - self._mcp_tools.keys():
                raise ToolError("A requested MCP tool is unavailable; no batch was dispatched")
            # Each client request owns its deadline. Do not discard completed peer results with
            # an outer Future.result timeout or start another batch before cancellation settles.
            return self._submit(self._call_tools_async(params=params, output_mode=output_mode))
        except Exception as error:
            message = (
                str(error)
                if isinstance(error, ToolError)
                else f"MCP batch failed ({type(error).__name__}); remote outcomes are unconfirmed"
            )
            return {"markdown": message, "results": [], "error": message}

    def _tool_texts_for_server(self, key: str) -> dict[str, str]:
        return {
            identity: tool.to_vdb_text(server_info=self._server_info_by_tool_id.get(identity, {}))
            for identity, tool in self._mcp_tools.items()
            if tool.server_key == key
        }

    async def _refresh_one_server(self, key: str) -> dict[str, Any]:
        result = {"added": [], "removed": [], "updated": [], "total": 0, "error": None}
        before = self._tool_texts_for_server(key)
        try:
            client = self._clients_by_key.get(key)
            if client is None:
                await self._connect_server(key)
            else:
                client.invalidate_cache()
                try:
                    tools = await client.list_tools()
                except Exception:
                    await self._release_client(client)
                    self._clients_by_key.pop(key, None)
                    raise
                self._replace_tools(key, client, tools)
            after = self._tool_texts_for_server(key)
            result.update(
                added=sorted(after.keys() - before.keys()),
                removed=sorted(before.keys() - after.keys()),
                updated=sorted(
                    identity
                    for identity in after.keys() & before.keys()
                    if after[identity] != before[identity]
                ),
                total=len(after),
            )
        except Exception as error:
            # The previous catalog remains intact until a complete listing is available.
            result["error"] = f"MCP refresh failed ({type(error).__name__})"
        return result

    async def _refresh_servers(self, keys: list[str]) -> dict[str, Any]:
        return {key: await self._refresh_one_server(key) for key in keys}

    def _refresh_tools(self, *, server_keys: list[str] | None = None) -> dict[str, Any]:
        try:
            keys = self._validate_keys(server_keys)
            servers = self._submit(self._refresh_servers(keys), timeout=DEFAULT_TIMEOUT)
            sync = (
                self._sync_tools_to_vdb()
                if any(info["error"] is None for info in servers.values())
                else {"error": None}
            )
            return {"servers": servers, "error": sync["error"]}
        except Exception as error:
            return {"servers": {}, "error": f"MCP refresh failed ({type(error).__name__})"}

    def initialize(self) -> None:
        if self._closed or self._initialized or self._loop_thread is not None:
            raise RuntimeError("MCP runner can only initialize once")
        config = json.loads(os.getenv("MCP_VDB_CONFIG", "{}"))
        servers = json.loads(os.getenv("MCP_SERVERS", "{}"))
        if not isinstance(servers, dict) or not servers or len(servers) > 64:
            raise ValueError("MCP requires between one and 64 configured servers")
        for key, values in servers.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("MCP server keys must be nonempty names")
            self._servers[key] = MCPServerConfig.model_validate(values).model_dump()
        self._collection_name = config.get("collection_name")
        if not self._collection_name:
            raise ValueError("collection_name is required in MCP_VDB_CONFIG")
        embedding = config.get("embedding") or {}
        if not embedding.get("provider") or not embedding.get("model"):
            raise ValueError("MCP embedding.provider and embedding.model are required")
        vdb_config = {key: value for key, value in config.items() if key != "embedding"}
        if not vdb_config.get("client_path"):
            vdb_config["client_path"] = str(
                WorkspacePaths.from_env()
                .data.indexes.namespace(AvatarModule.MCP.value)
                .backend("lancedb")
                .root
            )
        self._client = lancedb.get_client(**vdb_config)
        self._embeddings = create_embedding_model(
            ProviderTaskConfig(
                kind=ProviderKind.EMBEDDING,
                provider=embedding["provider"],
                model=embedding["model"],
                extra=embedding.get("extra") or {},
            )
        )
        dimension = len(self._embeddings.embed_query("dimension-probe"))
        self._ensure_collection(self._collection_name, dimension)
        self._loop_thread = AsyncLoopThread(name="mcp-loop")
        try:
            self._submit(self._initialize_mcp(), timeout=DEFAULT_TIMEOUT)
            sync = self._sync_tools_to_vdb()
            if sync["error"]:
                raise RuntimeError(sync["error"])
            self._initialized = True
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    def run(self, data: bytes) -> bytes:
        if self._closed or not self._initialized:
            raise RuntimeError("MCP runner is not available")
        request = json.loads(data)
        match request["op"]:
            case MCPOp.TOOL_SEARCH:
                result = self._search_tools(**request["param"])
            case MCPOp.TOOL_CALL:
                result = self._call_tools(**request["param"])
            case MCPOp.REFRESH_TOOLS:
                result = self._refresh_tools(**request["param"])
            case _:
                raise ValueError("Unsupported MCP runner operation")
        return json.dumps(result, ensure_ascii=False, allow_nan=False).encode()

    async def _close_clients(self) -> None:
        results = await asyncio.gather(
            *(client.aclose() for client in tuple(self._owned_clients)), return_exceptions=True
        )
        errors = [result for result in results if isinstance(result, Exception)]
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, Exception):
                errors.append(RuntimeError("MCP client cleanup cancelled itself"))
        self._clients_by_key.clear()
        self._mcp_tools.clear()
        self._server_info_by_tool_id.clear()
        self._tool_server_key.clear()
        self._owned_clients.clear()
        if errors:
            raise ExceptionGroup("MCP client cleanup failed", errors)

    def close(self) -> None:
        if self._closed:
            if self._close_error is not None:
                raise self._close_error
            return
        self._closed = True
        self._initialized = False
        errors = []
        if self._loop_thread is not None:
            try:
                self._submit(self._close_clients(), timeout=DEFAULT_TIMEOUT)
            except Exception as error:
                errors.append(error)
            try:
                self._loop_thread.stop(timeout=DEFAULT_TIMEOUT)
            except Exception as error:
                errors.append(error)
            else:
                self._loop_thread = None
        self._tool_table = self._client = self._embeddings = None
        if errors:
            self._close_error = ExceptionGroup("MCP runner cleanup failed", errors)
            raise self._close_error
