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


class RAGOp(StrEnum):
    QUERY = "query"
    INDEXING = "indexing"


class RAGBase(ABC):
    """Base class for RAG API tools."""

    name = "RAG"
    description = """Retrieve and ground answers using Retrieval-Augmented Generation (RAG).

This tool is designed for working with user-provided or locally stored content (files, documents, or web snapshots) and enabling fast, grounded retrieval later.

Use this tool when the task involves one or more of the following:
- Answering questions based on specific user-owned documents (PDF / Markdown / text / HTML)
- Grounding responses with explicit sources instead of general model knowledge
- Searching across a growing local knowledge base (notes, reports, manuals, web pages)
- Persisting knowledge so it can be reused efficiently in future conversations

Indexing vs Querying:
- Use indexing() to ingest and persist content into a searchable index.
- Use query() to retrieve relevant chunks from an existing index and generate answers.

When to consider indexing():
- The user explicitly asks to "save", "store", "remember", or "archive" a file, document, or webpage
- The user provides files or URLs and implies future reuse (e.g. “以后可能会用到”, “留着查”, “做个资料库”)
- The user downloads or collects multiple documents (e.g. via DeepResearch) that may be queried later
- The same or similar documents are referenced repeatedly across turns

When the user requests content but indexing intent is unclear:
- Ask a clarifying question such as:
  “Do you want me to build an index for this so you can search it later?”
- If the user confirms, call indexing(); otherwise, treat the content as temporary context only

Typical workflow:
1) Acquire content (uploaded files, local paths, or downloaded web pages).
2) Optionally ask the user whether the content should be indexed for future retrieval.
3) Use indexing() to build or update the index.
4) Use query() to retrieve relevant chunks and produce grounded answers.

Notes:
- indexing() supports both individual file paths and directories containing many files.
- Indexing is incremental: calling it multiple times will extend or refresh the existing index."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__()

    @abstractmethod
    async def query(
        self,
        *,
        query: str,
        ctx: RunContext | None = None,
        data_source: str = "all",
    ) -> str: ...

    @abstractmethod
    async def indexing(
        self,
        *,
        file_paths_or_dir: list[str],
        ctx: RunContext | None = None,
        data_source: str = "all",
    ) -> str: ...


class RAGAPI(ToolBase):
    args_description = """Args:
    op:
        The operation to perform. One of:
        - "query": Retrieve from an existing index and return grounded results.
        - "indexing": Ingest documents into an index for later retrieval.

    data_source:
        The target corpus/index name. Use "all" to query across all available
        sources, or pass a specific collection key (e.g., "pdf", "web", "notes",
        "project_docs"). This allows multiple independent indexes.

    query:
        The user question. Required for op="query". Should be a natural-language
        question or instruction describing what you want to find in the indexed
        content.

    file_paths_or_dir:
        A list of filesystem paths to files and/or directories to ingest.
        Required for op="indexing".
        - If a path is a directory, the implementation should recursively ingest
          supported files inside it (commonly: .pdf, .md, .txt).
        - If a path is a file, ingest that single file.

Expected returns by op:
    - query(data_source, query) -> retrieval results and/or grounded answer
      (implementation-defined, e.g., list of passages with metadata, plus a synthesis)
    - indexing(data_source, file_paths_or_dir) -> indexing status/summary
      (implementation-defined, e.g., counts of documents/chunks, doc_ids, errors)
"""

    def __init__(self, rag_object: RAGBase):
        super().__init__(
            name=rag_object.name,
            description=rag_object.description + "\n\n" + self.args_description,
        )

        self._rag_object = rag_object

    async def invoke(
        self,
        ctx: RunContext,
        op: Literal[RAGOp.QUERY, RAGOp.INDEXING],
        data_source: str = "all",
        query: str | None = None,
        file_paths_or_dir: list[str] | None = None,
    ) -> Any:
        match op:
            case RAGOp.QUERY:
                return await self._rag_object.query(query=query, ctx=ctx, data_source=data_source)
            case RAGOp.INDEXING:
                return await self._rag_object.indexing(
                    file_paths_or_dir=file_paths_or_dir, ctx=ctx, data_source=data_source
                )

    async def query(
        self,
        query: str,
        data_source: str = "all",
    ):
        return await self._rag_object.query(query=query, data_source=data_source)
