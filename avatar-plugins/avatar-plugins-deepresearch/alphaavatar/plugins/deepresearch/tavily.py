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
import os
from typing import Literal

from livekit.agents import NOT_GIVEN, NotGivenOr, RunContext
from tavily import TavilyClient

from alphaavatar.agents.tools import ToolBase

from .log import logger


class TavilyDeepResearchTool(ToolBase):
    name = "tavily_deepresearch"
    description = """Perform deep web research on a given topic using Tavily DeepResearch.

This tool is best used when the task requires:
- Broad information gathering from multiple sources
- Exploratory research on unfamiliar or complex topics
- Collecting background knowledge, trends, or comparisons
- Answering open-ended questions that cannot be resolved from a single source

It leverages Tavily's DeepResearch capabilities to search the web with
configurable depth and result limits.

Args:
    query: The research question or topic to search for. Should be a natural
        language description of what information is needed.
    search_depth: The depth of the search.
        - "basic": Faster, lighter search suitable for quick overviews.
        - "advanced": Deeper, more comprehensive search across more sources.
    max_results: The maximum number of search results to return.
        Higher values provide broader coverage but may include more noise."""

    def __init__(self, *args, tavily_api_key: NotGivenOr[str] = NOT_GIVEN, **kwargs) -> None:
        super().__init__(
            name=TavilyDeepResearchTool.name, description=TavilyDeepResearchTool.description
        )

        self._tavily_api_key = tavily_api_key or (os.getenv("TAVILY_API_KEY") or NOT_GIVEN)
        if not self._tavily_api_key:
            raise ValueError("TAVILY_API_KEY must be set by arguments or environment variables")

        self._tavily_client = TavilyClient(api_key=self._tavily_api_key)

    async def invoke(
        self,
        ctx: RunContext,
        query: str,
        search_depth: Literal["basic", "advanced"] = "basic",
        max_results: int = 5,
    ) -> dict:
        res = self._tavily_client.search(
            query=query, search_depth=search_depth, max_results=max_results
        )

        logger.debug(f"[TavilyDeepResearchTool] search result: {res}")
        return res
