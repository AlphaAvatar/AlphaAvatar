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
from livekit.agents.llm import ToolError

from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime.plugin import AvatarModule
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
    description = """Search and research the public web.

Use this tool for public-internet information, especially:
- Current or time-sensitive facts, such as stock prices, company or market
  information, news, recent events, schedules, and product information
- Direct factual web lookups that require fresh external information
- Broad or exploratory research across multiple public sources
- Comparisons, trends, background research, and evidence synthesis
- Fetching, extracting, or downloading known web pages

Routing rules:
- For a direct current fact or quick public-web lookup, use op="search".
- For a complex question requiring multiple sources, comparison, or synthesis,
  use op="research".
- Use op="scrape" only when URLs are already known and their page contents
  need to be extracted.
- Use op="download" only when URLs need to be saved as PDF artifacts.
- Prefer this tool over MCP for general public-web information.
- MCP is limited to capabilities explicitly exposed by its configured servers;
  it is not a general public-web search fallback.

Operations:
- search:
    Fast public-web search for a direct fact or recent information.
- research:
    Deeper multi-source public-web research and synthesis.
- scrape:
    Fetch known URLs and return integrated Markdown content.
- download:
    Fetch known URLs and save them as PDF artifacts.
"""

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
        Operation to perform:
        - "search": Default for direct current facts and quick public-web
          lookups, including prices, news, company information, recent events,
          schedules, and product information.
        - "research": Use for multi-source analysis, comparison, investigation,
          and synthesis.
        - "scrape": Extract and merge contents from known URLs.
        - "download": Download known URLs as stored PDF artifacts.

    query:
        Required for "search" and "research". Describe exactly what current
        public information or research result is needed.

    urls:
        Required for "scrape" and "download".

    monologue:
        Optional short user-facing status message. Keep it natural, brief,
        and in the user's language. Do not reveal hidden reasoning.

Expected returns:
    - search(query): public-web search results
    - research(query): multi-source findings and synthesis
    - scrape(urls): integrated Markdown
    - download(urls): stored PDF references
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
        self._current_op: DeepResearchOp | None = None

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

    def _status_source(self):
        return AvatarModule.DEEPRESEARCH

    def _status_stage(self):
        return self._current_op or "tool_error"

    async def invoke(
        self,
        ctx: RunContext,
        op: Literal[
            DeepResearchOp.SEARCH,
            DeepResearchOp.RESEARCH,
            DeepResearchOp.SCRAPE,
            DeepResearchOp.DOWNLOAD,
        ] = DeepResearchOp.SEARCH,
        query: str | None = None,
        urls: list[str] | None = None,
        monologue: str | None = None,
    ) -> Any:
        try:
            op = DeepResearchOp(op)
        except ValueError:
            msg = f"Unsupported DeepResearch operation: {op}"
            logger.error(msg)
            raise ToolError(msg)

        if op in {DeepResearchOp.SEARCH, DeepResearchOp.RESEARCH} and not query:
            raise ToolError(f"DeepResearch {op.value} requires a non-empty query.")

        if op in {DeepResearchOp.SCRAPE, DeepResearchOp.DOWNLOAD} and not urls:
            raise ToolError(f"DeepResearch {op.value} requires at least one URL.")

        self._current_op = op

        try:
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
        finally:
            self._current_op = None

        return result
