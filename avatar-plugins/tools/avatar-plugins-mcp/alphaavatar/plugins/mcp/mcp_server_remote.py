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
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, TypeVar

from alphaavatar.agents.tools.schemas import ToolError
from alphaavatar.core.cleanup import wait_for_cleanup
from mcp import ClientSession
from mcp.types import CallToolResult

from .config import MCPServerConfig
from .log import logger, redact_url
from .mcp_tool import MCPTool

T = TypeVar("T")


class MCPServerRemote:
    """One task enters and exits the MCP transport and ClientSession cancel scopes."""

    def __init__(self, *, server_key: str | None = None, **config: Any) -> None:
        self._config = MCPServerConfig.model_validate(config)
        self._server_key = server_key

        self._server_name: str | None = None
        self._server_title: str | None = None
        self._server_instruction = self._config.instruction

        self._loop = asyncio.get_running_loop()
        self._client: ClientSession | None = None
        self._owner: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] = self._loop.create_future()
        self._ready.add_done_callback(self._observe)
        self._stop = asyncio.Event()
        self._closing = False
        self._requests: set[asyncio.Task[Any]] = set()
        self._tools: tuple[MCPTool, ...] | None = None
        self._cache_generation = 0
        self._cached_generation = -1
        self._list_lock = asyncio.Lock()

    @property
    def url(self) -> str:
        return self._config.url

    @property
    def info_dict(self) -> dict[str, Any]:
        return {
            "key": self._server_key,
            "name": self._server_name,
            "title": self._server_title,
            "url": redact_url(self.url),
            "instruction": self._server_instruction,
        }

    @property
    def info(self) -> str:
        return json.dumps(self.info_dict, ensure_ascii=False)

    @staticmethod
    def _observe(task: asyncio.Future) -> None:
        if not task.cancelled():
            task.exception()

    def _check_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("MCP operations must run on their owning event loop")

    def _transport(self):
        options = {
            "headers": self._config.headers,
            "timeout": self._config.client_session_timeout_seconds,
            "sse_read_timeout": self._config.client_session_timeout_seconds,
        }
        if self._config.transport == "sse":
            from mcp.client.sse import sse_client

            return sse_client(self.url, **options)
        from mcp.client.streamable_http import streamablehttp_client

        return streamablehttp_client(self.url, **options, terminate_on_close=True)

    async def _settle_requests(self, *, cancel: bool) -> None:
        tasks = tuple(self._requests)
        if not tasks:
            return
        if cancel:
            for task in tasks:
                if not task.done():
                    task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _serve(self) -> None:
        try:
            # AnyIO-backed contexts must be exited by the task which entered them.
            async with self._transport() as streams:
                async with ClientSession(
                    streams[0],
                    streams[1],
                    read_timeout_seconds=timedelta(
                        seconds=self._config.client_session_timeout_seconds
                    ),
                ) as client:
                    self._client = client
                    async with asyncio.timeout(self._config.client_session_timeout_seconds):
                        result = await client.initialize()
                    if self._closing:
                        return
                    self._server_name = result.serverInfo.name
                    self._server_title = result.serverInfo.title
                    if self._server_instruction is None:
                        self._server_instruction = result.instructions
                    self._ready.set_result(None)
                    await self._stop.wait()
                    if self._requests:
                        _, pending = await asyncio.wait(
                            tuple(self._requests), timeout=self._config.close_timeout
                        )
                        await self._settle_requests(cancel=bool(pending))
                        if pending:
                            raise RuntimeError("MCP close deadline expired with calls in flight")
        finally:
            self._client = None
            self._closing = True
            self.invalidate_cache()
            # The close task joins these after all owner cancel scopes have unwound.
            for task in tuple(self._requests):
                if not task.done():
                    task.cancel()

    def _owner_done(self, task: asyncio.Task[None]) -> None:
        if not self._ready.done():
            self._ready.set_exception(RuntimeError("MCP connection did not become ready"))
        self._observe(task)
        self._begin_close()

    async def initialize(self) -> None:
        self._check_loop()
        if self._closing:
            raise RuntimeError("MCP server is closing or closed")
        if self._owner is None:
            self._owner = asyncio.create_task(self._serve(), name="mcp_connection")
            self._owner.add_done_callback(self._owner_done)
        try:
            await asyncio.shield(self._ready)
            if self._closing or self._owner.done():
                raise RuntimeError("MCP connection ended during initialization")
        except BaseException as original:
            try:
                await self.aclose()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def _request(self, operation: Callable[[ClientSession], Awaitable[T]]) -> T:
        self._check_loop()
        if self._closing or self._client is None or not self._ready.done():
            raise ToolError("MCP connection is unavailable; no request was dispatched")
        if len(self._requests) >= self._config.max_in_flight:
            raise ToolError("MCP request capacity is exhausted; no request was dispatched")
        client = self._client

        async def invoke() -> T:
            async with asyncio.timeout(self._config.client_session_timeout_seconds):
                return await operation(client)

        task = asyncio.create_task(invoke(), name="mcp_request")
        self._requests.add(task)
        task.add_done_callback(self._requests.discard)
        task.add_done_callback(self._observe)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()

            async def settle() -> None:
                await asyncio.gather(task, return_exceptions=True)

            await wait_for_cleanup(asyncio.create_task(settle(), name="mcp_request_cleanup"))
            raise

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        try:
            return await self._request(
                lambda client: client.call_tool(
                    name,
                    arguments=arguments,
                    read_timeout_seconds=timedelta(
                        seconds=self._config.client_session_timeout_seconds
                    ),
                )
            )
        except ToolError:
            raise
        except Exception as error:
            logger.warning("MCP invocation failed error_type=%s", type(error).__name__)
            raise ToolError(
                "MCP response was not confirmed; do not automatically replay the call"
            ) from None

    def invalidate_cache(self) -> None:
        self._cache_generation += 1

    async def list_tools(self) -> list[MCPTool]:
        self._check_loop()
        async with self._list_lock:
            if self._closing:
                raise RuntimeError("MCP server is closing or closed")
            generation = self._cache_generation
            if self._tools is not None and self._cached_generation == generation:
                return list(self._tools)
            tools: dict[str, MCPTool] = {}
            cursors: set[str] = set()
            cursor = None
            for _ in range(self._config.max_pages):
                page = await self._request(
                    lambda client, cursor=cursor: client.list_tools(cursor=cursor)
                )
                for item in page.tools:
                    if item.name in tools or len(tools) >= self._config.max_tools:
                        raise ValueError("Duplicate MCP tool name or listing limit exceeded")
                    tools[item.name] = MCPTool(
                        self.call_tool,
                        self._server_name,
                        item.name,
                        item.description,
                        item.inputSchema,
                        item.meta,
                        server_key=self._server_key,
                        annotations=item.annotations.model_dump(exclude_none=True)
                        if item.annotations is not None
                        else None,
                    )
                cursor = page.nextCursor
                if cursor is None:
                    result = tuple(tools.values())
                    if generation == self._cache_generation:
                        self._tools, self._cached_generation = result, generation
                    return list(result)
                if not cursor or cursor in cursors:
                    raise ValueError("MCP tool listing repeated a pagination cursor")
                cursors.add(cursor)
            raise ValueError("MCP tool listing exceeded its page limit")

    async def _close(self) -> None:
        results = []
        if self._owner is not None:
            results = await asyncio.gather(self._owner, return_exceptions=True)
        await self._settle_requests(cancel=True)
        self._tools = None
        for result in results:
            if isinstance(result, BaseException):
                raise RuntimeError("MCP connection cleanup failed") from result

    def _begin_close(self) -> asyncio.Task[None]:
        self._closing = True
        self._stop.set()
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="mcp_connection_close")
            self._close_task.add_done_callback(self._observe)
        return self._close_task

    async def aclose(self) -> None:
        self._check_loop()
        await wait_for_cleanup(self._begin_close())
