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

from typing import TYPE_CHECKING

from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin

from ..version import __version__

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.provider.base import LLMBase, WorkerEmbeddingBase
    from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig


class LangChainLLMPlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__("LangChain LLM", __version__, __name__)

    def get_plugin(self, *, config: ProviderTaskConfig) -> LLMBase:
        from .llms import LangChainLLM

        return LangChainLLM(config)


class LangChainEmbeddingPlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__("LangChain embedding", __version__, __name__)

    def get_plugin(self, *, config: ProviderTaskConfig) -> WorkerEmbeddingBase:
        from .embeddings import LangChainEmbedding

        return LangChainEmbedding(config)


AvatarModulePlugin.register(
    AvatarModule.PROVIDER_LLM,
    "langchain",
    LangChainLLMPlugin(),
)
AvatarModulePlugin.register(
    AvatarModule.PROVIDER_EMBEDDING,
    "langchain",
    LangChainEmbeddingPlugin(),
)
