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
from typing import Protocol

from alphaavatar.agents.avatar.context.schema import ContextBuildRequest, ContextBuildResult
from alphaavatar.agents.providers.schema import ModelInputType


class PromptRenderer(Protocol):
    def render(self, request: ContextBuildRequest) -> ContextBuildResult: ...


class RendererRegistry:
    def __init__(self) -> None:
        self._renderers: dict[ModelInputType, PromptRenderer] = {}

    def register(
        self,
        *,
        input_type: ModelInputType,
        renderer: PromptRenderer,
    ) -> None:
        self._renderers[input_type] = renderer

    def resolve(self, input_type: ModelInputType) -> PromptRenderer:
        try:
            return self._renderers[input_type]
        except KeyError as exc:
            raise ValueError(f"No PromptRenderer registered for {input_type.value!r}") from exc
