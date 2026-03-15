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
        instruction: str | None = None,
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
        self._server_instruction: str | None = instruction

        # Must be constructed inside the MCP loop thread so MCPTool can marshal calls back to this loop.
        self._initialized = False
        self._loop = asyncio.get_running_loop()
        self._init_lock = asyncio.Lock()

    @property
    def info_dict(self) -> dict[str, Any]:
        return {
            "name": self._server_name,
            "title": self._server_title,
            "url": self.url,
            "instruction": self._server_instruction,
        }

    @property
    def info(self) -> str:
        return json.dumps(self.info_dict, ensure_ascii=False)

    async def initialize(self) -> None:
        async with self._init_lock:
            if self._initialized:
                logger.debug("[MCPServerRemote] already initialized url=%s", self.url)
                return

            start = time.perf_counter()
            logger.info("[MCPServerRemote] initialize start url=%s", self.url)

            try:
                logger.debug("[MCPServerRemote] entering client_streams url=%s", self.url)
                streams = await self._exit_stack.enter_async_context(self.client_streams())
                receive_stream, send_stream = streams[0], streams[1]

                logger.debug("[MCPServerRemote] entering ClientSession url=%s", self.url)
                self._client = await self._exit_stack.enter_async_context(
                    ClientSession(
                        receive_stream,
                        send_stream,
                        read_timeout_seconds=timedelta(seconds=self._read_timeout)
                        if self._read_timeout
                        else None,
                    )
                )

                logger.debug("[MCPServerRemote] sending initialize request url=%s", self.url)
                init_result = await self._client.initialize()

                self._server_name = init_result.serverInfo.name if init_result.serverInfo else None
                self._server_title = (
                    init_result.serverInfo.title if init_result.serverInfo else None
                )
                self._server_instruction = (
                    init_result.instructions
                    if self._server_instruction is None
                    else self._server_instruction
                )
                self._initialized = True

                logger.info(
                    "[MCPServerRemote] initialize success url=%s elapsed=%.2fs name=%s title=%s",
                    self.url,
                    time.perf_counter() - start,
                    self._server_name,
                    self._server_title,
                )

            except asyncio.CancelledError:
                logger.exception(
                    "[MCPServerRemote] initialize cancelled url=%s elapsed=%.2fs",
                    self.url,
                    time.perf_counter() - start,
                )
                try:
                    await self.aclose()
                except Exception:
                    logger.exception("[MCPServerRemote] cleanup failed url=%s", self.url)
                raise

            except Exception:
                logger.exception(
                    "[MCPServerRemote] initialize failed url=%s elapsed=%.2fs",
                    self.url,
                    time.perf_counter() - start,
                )
                try:
                    await self.aclose()
                except Exception:
                    logger.exception("[MCPServerRemote] cleanup failed url=%s", self.url)
                raise

    async def list_tools(self) -> list[MCPTool]:
        if self._client is None:
            raise RuntimeError(f"MCPServer isn't initialized: url={self.url}")

        if not self._cache_dirty and self._lk_tools is not None:
            logger.debug(
                "[MCPServerRemote] list_tools cache hit url=%s count=%d",
                self.url,
                len(self._lk_tools),
            )
            return self._lk_tools

        start = time.perf_counter()
        tools = await self._client.list_tools()
        lk_tools = [
            self._make_tool_cls(tool.name, tool.description, tool.inputSchema, tool.meta)
            for tool in tools.tools
        ]

        self._lk_tools = lk_tools
        self._cache_dirty = False
        logger.info(
            "[MCPServerRemote] listed tools url=%s count=%d elapsed=%.2fs",
            self.url,
            len(lk_tools),
            time.perf_counter() - start,
        )
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
            "[MCPServerRemote] registered tool=%s server=%s",
            tool._tool_id,
            self._server_name,
        )
        logger.debug(
            "[MCPServerRemote] tool=%s input_schema=%s meta=%s",
            tool._tool_id,
            json.dumps(input_schema, ensure_ascii=False),
            json.dumps(meta, ensure_ascii=False) if meta is not None else None,
        )
        return tool

    async def aclose(self) -> None:
        try:
            await super().aclose()
        finally:
            self._client = None
            self._initialized = False
            self._lk_tools = None
            self._cache_dirty = True
