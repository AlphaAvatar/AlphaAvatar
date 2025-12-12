# Copyright 2025 AlphaAvatar project
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
from typing import Any

from livekit.agents import RunContext, function_tool, llm


class ToolBase(ABC):
    """Base class for all tools used by agents in the AlphaAvatar framework."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

        @function_tool(name=self.name, description=self.description)
        async def _tool(ctx: "RunContext", *args, **kwargs) -> Any:
            return await self.invoke(ctx, *args, **kwargs)

        self._tool = _tool

    @property
    def tool(self) -> llm.FunctionTool | llm.RawFunctionTool:
        return self._tool

    @abstractmethod
    async def invoke(self, ctx: "RunContext", *args, **kwargs) -> Any: ...
