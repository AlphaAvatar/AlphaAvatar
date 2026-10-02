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
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager

from pydantic import BaseModel

from .schemas.model_input import ModelInput
from .schemas.model_result import ProviderModelResult
from .schemas.request import ModelRequest
from .schemas.stream import ModelStreamEvent


class LLMBase(ABC):
    @abstractmethod
    def validate_input(self, *, require_input_adapter: bool = False) -> None:
        """Validate configuration without making a model request."""

    @abstractmethod
    async def ainvoke_structured(
        self, model_input: ModelInput, *, output_schema: type[BaseModel], include_raw: bool = False
    ) -> ProviderModelResult:
        """Return a validated result without exposing SDK messages or runnable objects."""


class StreamingLLMBase(LLMBase):
    @abstractmethod
    def stream(
        self, request: ModelRequest
    ) -> AbstractAsyncContextManager[AsyncIterator[ModelStreamEvent]]:
        """Own one request stream; errors/cancellation propagate, exit closes the stream."""


class EmbeddingBase(ABC):
    @abstractmethod
    async def aembed_query(self, text: str) -> list[float]: ...

    @abstractmethod
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]: ...


class WorkerEmbeddingBase(EmbeddingBase):
    """Blocking entrypoints used only by existing isolated inference workers."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
