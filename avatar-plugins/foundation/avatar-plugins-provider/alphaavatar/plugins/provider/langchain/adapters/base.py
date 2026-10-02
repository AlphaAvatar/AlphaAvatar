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

from importlib import import_module
from typing import Any, Protocol

from alphaavatar.agents.avatar.provider.schemas import (
    ModelInput,
    ProviderTaskConfig,
)

_ADAPTERS = {
    "langchain_text": (".text", "LangChainTextInputAdapter"),
    "langchain_gemini": (".gemini", "LangChainGeminiInputAdapter"),
}


class InputAdapter(Protocol):
    async def adapt(
        self,
        model_input: ModelInput,
        *,
        config: ProviderTaskConfig,
    ) -> Any: ...


class LangChainInputAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, InputAdapter] = {}

    def resolve(self, name: str) -> InputAdapter:
        if name not in _ADAPTERS:
            raise ValueError(f"Unknown LangChain input adapter: {name!r}")
        if name not in self._adapters:
            module, symbol = _ADAPTERS[name]
            self._adapters[name] = getattr(import_module(module, __package__), symbol)()

        return self._adapters[name]
