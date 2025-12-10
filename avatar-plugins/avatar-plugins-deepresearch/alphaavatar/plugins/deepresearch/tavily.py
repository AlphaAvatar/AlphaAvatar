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
from livekit.agents import RunContext
from tavily import TavilyClient

from alphaavatar.agents.tools import ToolBase


class TavilyDeepSearchTool(ToolBase):
    name = "tavily_deepsearch"
    description = "Use this tool to perform deep research on a given topic using Tavily's DeepResearch capabilities."

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(
            name=TavilyDeepSearchTool.name, description=TavilyDeepSearchTool.description
        )

        self.tavily_client = TavilyClient(api_key="tvly-YOUR_API_KEY")

    async def invoke(self, ctx: "RunContext", query: str, max_results: int = 5) -> dict:
        # TODO
        ...
