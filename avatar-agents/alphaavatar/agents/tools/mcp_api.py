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
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, Literal

from livekit.agents import RunContext

from alphaavatar.agents.log import logger

from .base import ToolBase


class MCPOp(StrEnum):
    TOOL_CALL = "tool_call"


class MCPHostBase(ABC):
    name = "MCP Tools"
    description = None

    def __init__(self, description, *args, **kwargs) -> None:
        super().__init__()
        self.description = description

    @abstractmethod
    async def call_tools(self, *, params: dict, ctx: RunContext) -> Any: ...


class MCPAPI(ToolBase):
    def __init__(self, mcp_host: MCPHostBase) -> None:
        if mcp_host.description is None:
            logger.warning("MCP Host must have a description for the MCP API tool.")
            return

        super().__init__(name=mcp_host.name, description=mcp_host.description)

        self._mcp_host = mcp_host

    async def invoke(
        self,
        ctx: RunContext,
        op: Literal[MCPOp.TOOL_CALL,],
        params: dict,
    ) -> Any:
        match op:
            case MCPOp.TOOL_CALL:
                return await self._mcp_host.call_tools(params=params, ctx=ctx)
            case _:
                msg = f"Unsupported MCP operation: {op}"
                logger.error(msg)
                return msg
