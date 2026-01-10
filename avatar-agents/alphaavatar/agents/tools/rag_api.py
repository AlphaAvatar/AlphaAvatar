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
from enum import StrEnum
from typing import Any, Literal

from livekit.agents import RunContext

from .base import ToolBase


class RAGOp(StrEnum):
    BASIC = "basic"
    ADVANCED = "advanced"


class RAGBase:
    """Base class for RAG API tools."""

    def __init__(self, *, name: str, description: str):
        self.name = name
        self.description = description


class RAGAPI(ToolBase):
    def __init__(self, rag_object: RAGBase):
        super().__init__(name=rag_object.name, description=rag_object.description)

        self._rag_object = rag_object

    async def invoke(
        self,
        ctx: RunContext,
        query: str,
        search_depth: Literal["basic", "advanced"] = "basic",
        max_results: int = 5,
    ) -> Any:
        pass
