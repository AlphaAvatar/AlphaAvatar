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
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from alphaavatar.agents.tools.schemas import ToolError

if TYPE_CHECKING:
    from mcp.types import CallToolResult


class MCPTool:
    """Borrow a bounded invocation callback; never own or reopen an MCP connection."""

    def __init__(
        self,
        invoke: Callable[[str, dict[str, Any]], Awaitable[CallToolResult]],
        client_name: str | None,
        name: str,
        description: str | None,
        input_schema: dict[str, Any],
        meta: dict[str, Any] | None,
        server_key: str | None = None,
        annotations: dict[str, Any] | None = None,
    ) -> None:
        self._invoke = invoke
        self._client_name, self._server_key = client_name, server_key
        self._name, self._description = name, description
        self._input_schema, self._meta = input_schema, meta
        self._annotations = annotations or {}

        prefix = server_key or client_name
        self._tool_id = f"{prefix}.{name}" if prefix else name

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def client_name(self) -> str | None:
        return self._client_name

    @property
    def server_key(self) -> str | None:
        return self._server_key

    @property
    def category(self) -> str:
        read_only = self._annotations.get("readOnlyHint")
        if read_only is True:
            return "read"
        if read_only is False:
            return "write"
        return "unknown"

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def meta(self) -> dict[str, Any] | None:
        return self._meta

    @property
    def description_text(self) -> str:
        return self._description or ""

    @property
    def description(self) -> str:
        description = (
            f"{self._tool_id}: {self._description} "
            f"(input schema: {self._input_schema}, meta: {self._meta})"
        )
        return re.sub(r"\s+", " ", description).strip()

    def to_vdb_text(self, *, server_info: dict[str, Any] | None = None) -> str:
        return json.dumps(
            {
                "tool_id": self._tool_id,
                "server_key": self._server_key,
                "server_name": self._client_name,
                "name": self._name,
                "description": self._description,
                "input_schema": self._input_schema,
                "meta": self._meta,
                "server_info": server_info or {},
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    async def call(self, raw_arguments: dict[str, Any]) -> str:
        # Dispatch exactly once. Transport failure cannot prove that a remote write was undone.
        result = await self._invoke(self._name, raw_arguments)
        if result.isError:
            raise ToolError("MCP tool reported failure; remote side effects may already exist")
        content = [part.model_dump(mode="json") for part in result.content]
        if result.structuredContent is not None:
            return json.dumps(
                {"content": content, "structuredContent": result.structuredContent},
                ensure_ascii=False,
            )
        # Empty content is a valid successful MCP response, not evidence of execution failure.
        return json.dumps(content[0] if len(content) == 1 else content, ensure_ascii=False)
