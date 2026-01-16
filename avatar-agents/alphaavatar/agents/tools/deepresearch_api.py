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

from livekit.agents import NOT_GIVEN, NotGivenOr, RunContext

from .base import ToolBase


class DeepResearchOp(StrEnum):
    SEARCH = "search"
    RESEARCH = "research"
    SCRAPE = "scrape"
    DOWNLOAD = "download"


class DeepResearchBase(ABC):
    """Base class for RAG API tools."""
    name = "DeepResearch"
    description = """Perform deep web research on a given topic using Tavily DeepResearch.

This tool is best used when the task requires:
- Broad information gathering from multiple sources
- Exploratory research on unfamiliar or complex topics
- Collecting background knowledge, trends, or comparisons
- Answering open-ended questions that cannot be resolved from a single source

It leverages Tavily's DeepResearch capabilities to search the web with
configurable depth and result limits."""

    def __init__(self, *args, **kwargs): ...

    @abstractmethod
    async def search(
        self,
        ctx: RunContext,
        query: NotGivenOr[str] = NOT_GIVEN,
    ) -> Any: ...

    @abstractmethod
    async def research(
        self,
        ctx: RunContext,
        query: NotGivenOr[str] = NOT_GIVEN,
    ) -> Any: ...

    @abstractmethod
    async def scrape(
        self,
        ctx: RunContext,
        urls: NotGivenOr[list[str]] = NOT_GIVEN,
    ) -> Any: ...

    @abstractmethod
    async def download(
        self,
        ctx: RunContext,
        urls: NotGivenOr[list[str]] = NOT_GIVEN,
    ) -> Any: ...


class DeepResearchAPI(ToolBase):
    args_description = """
Args:
    query: The research question or topic to search for. Should be a natural
        language description of what information is needed.
    search_depth: The depth of the search.
        - "basic": Faster, lighter search suitable for quick overviews.
        - "advanced": Deeper, more comprehensive search across more sources."""

    def __init__(self, deepresearch_object: DeepResearchBase):
        super().__init__(
            name=deepresearch_object.name,
            description=deepresearch_object.description + "\n\n" + self.args_description,
        )

        self._deepresearch_object = deepresearch_object

    async def invoke(
        self,
        ctx: RunContext,
        op: Literal[DeepResearchOp.SEARCH, DeepResearchOp.RESEARCH, DeepResearchOp.SCRAPE, DeepResearchOp.DOWNLOAD],
        query: NotGivenOr[str] = NOT_GIVEN,
        urls: NotGivenOr[list[str]] = NOT_GIVEN,
    ) -> Any:
        match op:
            case DeepResearchOp.SEARCH:
                return await self._deepresearch_object.search(ctx, query=query)
            case DeepResearchOp.SEARCH:
                return await self._deepresearch_object.research(ctx, query=query)
            case DeepResearchOp.SCRAPE:
                return await self._deepresearch_object.scrape(ctx, urls=urls)
            case DeepResearchOp.DOWNLOAD:
                return await self._deepresearch_object.download(ctx, urls=urls)
