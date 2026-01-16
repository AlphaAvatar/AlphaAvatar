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
import pathlib

from livekit.agents import NOT_GIVEN, NotGivenOr, RunContext
from tavily import TavilyClient

from alphaavatar.agents.tools import DeepResearchBase

from .log import logger

SEARCH_INSTANCE = "tavily"


class TavilyDeepResearchTool(DeepResearchBase):
    def __init__(
        self,
        *args,
        working_dir: pathlib.Path,
        tavily_api_key: NotGivenOr[str] = NOT_GIVEN,
        **kwargs,
    ) -> None:
        super().__init__()

        self._working_dir = working_dir / SEARCH_INSTANCE
        self._tavily_api_key = tavily_api_key or (os.getenv("TAVILY_API_KEY") or NOT_GIVEN)

        if not self._tavily_api_key:
            raise ValueError("TAVILY_API_KEY must be set by arguments or environment variables")

        self._tavily_client = TavilyClient(api_key=self._tavily_api_key)

    async def search(
        self,
        ctx: RunContext,
        query: str,
    ) -> dict:
        logger.info(f"[TavilyDeepResearchTool] search func by query: {query}")
        res = self._tavily_client.search(query=query, search_depth="basic", max_results=5)
        return res

    async def research(
        self,
        ctx: RunContext,
        query: str,
    ) -> dict:
        logger.info(f"[TavilyDeepResearchTool] research func by query: {query}")
        res = self._tavily_client.search(query=query, search_depth="advanced", max_results=5)

        return res

    async def scrape(self, ctx, urls: list[str]) -> list[str]:
        logger.info(f"[TavilyDeepResearchTool] scrape func by urls: {urls}")
        res = self._tavily_client.extract(urls=urls, include_images=True)
        return res

    async def download(self, ctx, urls: list[str]) -> list[str]:
        logger.info(f"[TavilyDeepResearchTool] download func by urls: {urls}")
        res = self._tavily_client.extract(urls=urls, include_images=True)
        return res
