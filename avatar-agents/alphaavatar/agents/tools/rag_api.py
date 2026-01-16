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
    description = """"""

    def __init__(self, *args, **kwargs): ...

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
        file_path_or_dir: NotGivenOr[str] = NOT_GIVEN,
    ) -> Any: ...


class RAGAPI(ToolBase):
    args_description = ""

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
        file_path_or_dir: NotGivenOr[str] = NOT_GIVEN,
    ) -> Any:
        match op:
            case RAGOp.QUERY:
                return await self._rag_object.query(ctx, data_source=data_source, query=query)
            case RAGOp.INDEXING:
                return await self._rag_object.indexing(
                    ctx, data_source=data_source, file_path_or_dir=file_path_or_dir
                )

    async def query(
        self,
        ctx: RunContext,
        data_source: str = "all",
        query: NotGivenOr[str] = NOT_GIVEN,
    ):
        return await self._rag_object.query(ctx, data_source=data_source, query=query)
