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


class RAGOp(StrEnum):
    QUERY = "query"
    INDEXING = "indexing"


class RAGBase(ABC):
    """Base class for RAG API tools."""

    name = "RAG"
    description = """Retrieve and ground answers using Retrieval-Augmented Generation (RAG).

This tool is best used when the task requires:
- Answering questions using your own indexed documents (PDF/Markdown/text)
- Grounding responses with specific sources rather than general knowledge
- Searching across a large local corpus (notes, reports, web snapshots, manuals)
- Iteratively building and updating an index for later fast retrieval

Typical workflow:
1) Use indexing() to ingest files (e.g., PDFs downloaded from DeepResearch.download).
2) Use query() to retrieve relevant chunks and produce grounded answers.

Note:
- "data_source" controls which collection/index to use (e.g., "all", "pdf", "web", "notes").
- Indexing supports both individual file paths and directories containing many files."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__()

    @abstractmethod
    async def query(
        self,
        ctx: RunContext,
        data_source: str = "all",
        query: NotGivenOr[str] = NOT_GIVEN,
    ) -> Any: ...

    @abstractmethod
    async def indexing(
        self,
        ctx: RunContext,
        data_source: str = "all",
        file_paths_or_dir: NotGivenOr[list[str]] = NOT_GIVEN,
    ) -> Any: ...


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
        query: NotGivenOr[str] = NOT_GIVEN,
        file_paths_or_dir: NotGivenOr[list[str]] = NOT_GIVEN,
    ) -> Any:
        match op:
            case RAGOp.QUERY:
                return await self._rag_object.query(ctx, data_source=data_source, query=query)
            case RAGOp.INDEXING:
                return await self._rag_object.indexing(
                    ctx, data_source=data_source, file_paths_or_dir=file_paths_or_dir
                )

    async def query(
        self,
        ctx: RunContext,
        data_source: str = "all",
        query: NotGivenOr[str] = NOT_GIVEN,
    ):
        return await self._rag_object.query(ctx, data_source=data_source, query=query)
