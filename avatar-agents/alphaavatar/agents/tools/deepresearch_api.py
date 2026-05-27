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
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any, Literal

from livekit.agents import RunContext

from alphaavatar.agents import AvatarModule
from alphaavatar.agents.log import logger
from alphaavatar.agents.status import (
    StatusEmitter,
    StatusEvent,
    StatusPriority,
    StatusType,
)

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

    monologue:
        Optional short user-facing status message to show or speak while this
        tool is running. Keep it brief, natural, and in the same language as the
        user. Do not reveal hidden reasoning. Examples:
        - "我查一下。"
        - "我深入查一下。"
        - "I’ll check that."
        - "I’ll dig into it."

Expected returns by op:
    - search(query) -> search results (e.g., list of {title, url, snippet}, etc.)
    - research(query) -> enriched results + synthesis (e.g., ranked sources,
      key findings, structured summary)
    - scrape(urls) -> integrated Markdown string (merged content from all URLs)
    - download(urls) -> str of stored PDF file references/paths
"""

    def __init__(
        self,
        deepresearch_object: DeepResearchBase,
        *,
        status_emitter: StatusEmitter | None = None,
    ):
        super().__init__(
            name=deepresearch_object.name,
            description=deepresearch_object.description + "\n\n" + self.args_description,
            status_emitter=status_emitter,
        )

        self._deepresearch_object = deepresearch_object

    def _emit_op_status(
        self,
        *,
        op: DeepResearchOp,
        status_type: StatusType,
        query: str | None = None,
        urls: list[str] | None = None,
        monologue: str | None = None,
    ) -> None:
        metadata: dict[str, Any] = {
            "op": op.value,
        }

        if query is not None:
            metadata["query"] = query

        if urls is not None:
            metadata["url_count"] = len(urls)

        self.emit_status_nowait(
            StatusEvent(
                type=status_type,
                source=AvatarModule.DEEPRESEARCH,
                stage=op,
                message=monologue,
                priority=StatusPriority.NORMAL,
                metadata=metadata,
            )
        )

    def _should_emit_finalizing(self, op: DeepResearchOp) -> bool:
        return op in {
            DeepResearchOp.SEARCH,
            DeepResearchOp.RESEARCH,
        }

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
        monologue: str | None = None,
    ) -> Any:
        try:
            op = DeepResearchOp(op)
        except ValueError:
            msg = f"Unsupported DeepResearch operation: {op}"
            logger.error(msg)
            return msg

        handlers: dict[DeepResearchOp, Callable[[], Awaitable[Any]]] = {
            DeepResearchOp.SEARCH: lambda: self._deepresearch_object.search(
                query=query,
                ctx=ctx,
            ),
            DeepResearchOp.RESEARCH: lambda: self._deepresearch_object.research(
                query=query,
                ctx=ctx,
            ),
            DeepResearchOp.SCRAPE: lambda: self._deepresearch_object.scrape(
                urls=urls,
                ctx=ctx,
            ),
            DeepResearchOp.DOWNLOAD: lambda: self._deepresearch_object.download(
                urls=urls,
                ctx=ctx,
            ),
        }

        self._emit_op_status(
            op=op,
            status_type=StatusType.TOOL_START,
            query=query,
            urls=urls,
            monologue=monologue,
        )

        result = await handlers[op]()

        if self._should_emit_finalizing(op):
            self._emit_op_status(
                op=op,
                status_type=StatusType.FINALIZING,
            )

        return result
