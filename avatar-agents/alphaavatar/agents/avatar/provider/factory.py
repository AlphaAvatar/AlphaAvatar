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
from functools import cache
from importlib.metadata import entry_points

from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin

from .base import LLMBase, WorkerEmbeddingBase
from .enums import ProviderKind
from .schemas import ProviderTaskConfig


@cache
def _load_backend(name: str) -> None:
    matches = tuple(entry_points(group="alphaavatar.provider", name=name))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one installed provider backend {name!r}, found {len(matches)}"
        )
    matches[0].load()


def create_llm_model(config: ProviderTaskConfig) -> LLMBase:
    if config.kind != ProviderKind.LLM:
        raise ValueError("An LLM requires kind='llm'")
    _load_backend(config.backend)
    model = AvatarModulePlugin.create(AvatarModule.PROVIDER_LLM, config.backend, config=config)
    if not isinstance(model, LLMBase):
        raise TypeError("Provider LLM factory must return LLMBase")
    return model


def create_embedding_model(config: ProviderTaskConfig) -> WorkerEmbeddingBase:
    if config.kind != ProviderKind.EMBEDDING:
        raise ValueError("An embedding model requires kind='embedding'")
    _load_backend(config.backend)
    model = AvatarModulePlugin.create(
        AvatarModule.PROVIDER_EMBEDDING, config.backend, config=config
    )
    if not isinstance(model, WorkerEmbeddingBase):
        raise TypeError("Provider embedding factory must return WorkerEmbeddingBase")
    return model
