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

from .base import ToolBase


class DeepResearchOp(StrEnum):
    SEARCH = "search"
    RESEARCH = "research"
    SCRAPE = "scrape"
    DOWNLOAD = "download"


class DeepResearchBase(ABC):
    """Base class for RAG API tools."""

    name = "DeepResearch"
    description = """Perform deep web research and content acquisition for a given topic.

This tool is best used when the task requires:
- Broad information gathering from multiple sources
- Exploratory research on unfamiliar or complex topics
- Collecting background knowledge, trends, or comparisons
- Answering open-ended questions that cannot be resolved from a single source

It exposes four operations (op) that can be composed into a pipeline:
- search:
    Perform a lightweight web search for quick discovery. Use this when you
    need fast, broad results with minimal reasoning.
- research:
    Perform deep, multi-step research. Use this when the question requires
    decomposition, iterative searching, cross-source comparison, and reasoning.
- scrape:
    Given a list of URLs, fetch and extract the main page contents, then
    merge them into an integrated Markdown text suitable for downstream
    processing (e.g., summarization, indexing).
- download:
    Given a list of URLs, fetch pages and convert them into stored PDF
    artifacts, returning a list of stored file references (string list)
    for downstream tools/plugins (e.g., a RAG plugin building a local index)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__()

    @abstractmethod
    async def search(
        self,
        *,
        query: str,
        ctx: RunContext | None = None,
    ) -> str: ...

    @abstractmethod
    async def research(
        self,
        *,
        query: str,
        ctx: RunContext | None = None,
    ) -> str: ...

    @abstractmethod
    async def scrape(
        self,
        *,
        urls: list[str],
        ctx: RunContext | None = None,
    ) -> str: ...

    @abstractmethod
    async def download(
        self,
        *,
        urls: list[str],
        ctx: RunContext | None = None,
    ) -> str: ...


class DeepResearchAPI(ToolBase):
    args_description = """Args:
    op:
        The operation to perform. One of:
        - "search": Simple web search (fast discovery, minimal reasoning).
        - "research": Deep multi-step research (query decomposition, iterative
          searching, cross-source synthesis).
        - "scrape": Fetch the given URL list and return ONE integrated Markdown
          text that merges the extracted contents for assistant answering direct questions.
        - "download": Fetch the given URL list, convert pages to PDFs, store them to disk,
          and return a list of stored file references (strings) for downstream
          tools/plugins (e.g., RAG indexing func).

    query:
        The research question or search topic. Required for "search" and
        "research". Should be a natural-language description of what information
        is needed.

    urls:
        A list of URLs to process. Required for "scrape" and "download".
        Use URLs returned by "search" or "research".

Expected returns by op:
    - search(query) -> search results (e.g., list of {title, url, snippet}, etc.)
    - research(query) -> enriched results + synthesis (e.g., ranked sources,
      key findings, structured summary)
    - scrape(urls) -> integrated Markdown string (merged content from all URLs)
    - download(urls) -> str of stored PDF file references/paths
"""

    def __init__(self, deepresearch_object: DeepResearchBase):
        super().__init__(
            name=deepresearch_object.name,
            description=deepresearch_object.description + "\n\n" + self.args_description,
        )

        self._deepresearch_object = deepresearch_object

    async def invoke(
        self,
        ctx: RunContext,
        op: Literal[
            DeepResearchOp.SEARCH,
            DeepResearchOp.RESEARCH,
            DeepResearchOp.SCRAPE,
            DeepResearchOp.DOWNLOAD,
        ],
        query: str | None = None,
        urls: list[str] | None = None,
    ) -> Any:
        match op:
            case DeepResearchOp.SEARCH:
                return await self._deepresearch_object.search(query=query, ctx=ctx)
            case DeepResearchOp.RESEARCH:
                return await self._deepresearch_object.research(query=query, ctx=ctx)
            case DeepResearchOp.SCRAPE:
                return await self._deepresearch_object.scrape(urls=urls, ctx=ctx)
            case DeepResearchOp.DOWNLOAD:
                return await self._deepresearch_object.download(urls=urls, ctx=ctx)
