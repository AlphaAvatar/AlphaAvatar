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
from langchain_core.embeddings import Embeddings

from alphaavatar.agents.avatar.provider.base import WorkerEmbeddingBase
from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig

from .models import create_embedding_model


class LangChainEmbedding(WorkerEmbeddingBase, Embeddings):
    def __init__(self, config: ProviderTaskConfig) -> None:
        self._model = create_embedding_model(config.model_copy(deep=True))

    async def aembed_query(self, text: str) -> list[float]:
        return await self._model.aembed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._model.aembed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._model.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.embed_documents(texts)
