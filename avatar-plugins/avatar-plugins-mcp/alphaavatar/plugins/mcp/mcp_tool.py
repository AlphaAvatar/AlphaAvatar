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
import re
from typing import Any

from livekit.agents.llm.tool_context import ToolError

from mcp import ClientSession

from .config import DEFAULT_TIMEOUT


class MCPTool:
    def __init__(
        self,
        client: ClientSession,
        client_name: str | None,
        name: str,
        description: str | None,
        input_schema: dict[str, Any],
        meta: dict[str, Any] | None,
    ) -> None:
        self._client = client
        self._client_name = client_name

        self._name = name
        self._description = description
        self._input_schema = input_schema
        self._meta = meta

        self._tool_id = f"{client_name}.{name}" if client_name else name

    @property
    def description(self) -> str:
        description = f"{self._tool_id}: {self._description} (input schema: {self._input_schema}, meta: {self._meta})"
        description = re.sub(r"\s+", " ", description).strip()
        return description

    async def call(self, raw_arguments: dict[str, Any]) -> Any:
        # In case (somehow), the tool is called after the MCPServer aclose.
        if self._client is None:
            raise ToolError(
                "Tool invocation failed: internal service is unavailable. "
                "Please check that the MCPServer is still running."
            )

        try:
            tool_result = await asyncio.wait_for(
                self._client.call_tool(self._name, arguments=raw_arguments),
                timeout=DEFAULT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise ToolError(
                f"Tool '{self._tool_id}' timed out after {DEFAULT_TIMEOUT:.1f} seconds."
            )

        if tool_result.isError:
            error_str = "\n".join(str(part) for part in tool_result.content)
            raise ToolError(error_str)

        # TODO: handle images & binary messages
        if len(tool_result.content) == 1:
            return tool_result.content[0].model_dump_json()
        elif len(tool_result.content) > 1:
            return json.dumps([item.model_dump() for item in tool_result.content])

        raise ToolError(
            f"Tool '{self._name}' completed without producing a result. "
            "This might indicate an issue with internal processing."
        )
