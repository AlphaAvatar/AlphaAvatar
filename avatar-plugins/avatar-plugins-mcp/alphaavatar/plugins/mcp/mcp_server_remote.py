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
from datetime import timedelta
from typing import Any

from livekit.agents import mcp

from mcp import ClientSession

from .config import DEFAULT_TIMEOUT
from .log import logger
from .mcp_tool import MCPTool


class MCPServerRemote(mcp.MCPServerHTTP):
    def __init__(
        self,
        *,
        url: str,
        headers: dict[str, Any] | None = None,
        instrcution: str | None = None,
        client_session_timeout_seconds: float = DEFAULT_TIMEOUT,
        **kwargs,
    ) -> None:
        super().__init__(
            url=url,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
            client_session_timeout_seconds=client_session_timeout_seconds,
        )

        self._server_name: str | None = None
        self._server_title: str | None = None
        self._server_instrcution: str | None = instrcution

        self._loop = asyncio.get_running_loop()

    @property
    def info(self) -> str:
        info = {
            "name": self._server_name,
            "title": self._server_title,
            "url": self.url,
            "instrcution": self._server_instrcution,
        }
        return json.dumps(info, ensure_ascii=False)

    async def initialize(self) -> None:
        try:
            streams = await self._exit_stack.enter_async_context(self.client_streams())
            receive_stream, send_stream = streams[0], streams[1]
            self._client = await self._exit_stack.enter_async_context(
                ClientSession(
                    receive_stream,
                    send_stream,
                    read_timeout_seconds=timedelta(seconds=self._read_timeout)
                    if self._read_timeout
                    else None,
                )
            )
            init_result = await self._client.initialize()  # type: ignore[union-attr]
            self._server_name = init_result.serverInfo.name if init_result.serverInfo else None
            self._server_title = init_result.serverInfo.title if init_result.serverInfo else None
            self._server_instrcution = (
                init_result.instructions
                if self._server_instrcution is None
                else self._server_instrcution
            )
            self._initialized = True
            logger.info(
                f"[MCPServerRemote] Initialized MCPServerRemote success for client '{self.info}' at URL: {self.url}"
            )
        except Exception as e:
            logger.error(
                f"[MCPServerRemote] Initialized MCPServerRemote falied ❌ for client '{self.info}' at URL: {self.url}, {e}"
            )
            await self.aclose()
            raise

    async def list_tools(self) -> list[MCPTool]:
        if self._client is None:
            raise RuntimeError("MCPServer isn't initialized")

        if not self._cache_dirty and self._lk_tools is not None:
            return self._lk_tools

        tools = await self._client.list_tools()
        lk_tools = [
            self._make_tool_cls(tool.name, tool.description, tool.inputSchema, tool.meta)
            for tool in tools.tools
        ]

        self._lk_tools = lk_tools
        self._cache_dirty = False
        return lk_tools

    def _make_tool_cls(
        self,
        name: str,
        description: str | None,
        input_schema: dict[str, Any],
        meta: dict[str, Any] | None,
    ) -> MCPTool:
        tool = MCPTool(
            self._client,
            self._server_name,
            name,
            description,
            input_schema,
            meta,
            server_loop=self._loop,
        )
        logger.info(
            f"[MCPServerRemote] Registered MCP tool: {tool._tool_id} with input schema: {input_schema} and meta: {meta}"
        )
        return tool
