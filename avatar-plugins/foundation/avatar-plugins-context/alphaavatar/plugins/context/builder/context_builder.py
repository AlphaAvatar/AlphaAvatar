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

import hashlib
import json
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from alphaavatar.agents.avatar.context.schemas import ContextContribution
from alphaavatar.agents.avatar.provider.enums import ModelInputType, ModelRole
from alphaavatar.agents.avatar.provider.schemas import (
    ModelAudioPart,
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelImagePart,
    ModelInput,
    ModelInputMessage,
    ModelTextPart,
)
from alphaavatar.agents.constants import RUNTIME_CONTEXT_TOOL_NAME

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.context.schemas import ContextBuildRequest, ContextBuildResult

    from .renderer import RendererRegistry


class ContextBuilder:
    """Compose model inputs; synthetic runtime items are projections, not history or tool work."""

    SYSTEM_MESSAGE_ID = "alphaavatar.system"

    def __init__(self, registry: RendererRegistry | None = None) -> None:
        self._registry = registry

    def _renderers(self) -> RendererRegistry:
        if self._registry is None:
            from .renderer import RealtimeRenderer, RendererRegistry, TextRenderer, VLMRenderer

            self._registry = RendererRegistry()
            for kind, renderer in (
                (ModelInputType.TEXT, TextRenderer()),
                (ModelInputType.VLM, VLMRenderer()),
                (ModelInputType.REALTIME, RealtimeRenderer()),
            ):
                self._registry.register(input_type=kind, renderer=renderer)

        return self._registry

    @staticmethod
    def _is_runtime_context_item(item: object) -> bool:
        return (
            isinstance(item, ModelFunctionCall | ModelFunctionOutput)
            and item.name == RUNTIME_CONTEXT_TOOL_NAME
        )

    @staticmethod
    def _historical_media_placeholder(*, image_count: int, audio_count: int) -> ModelTextPart:
        return ModelTextPart(
            '<historical_media omitted="true" current="false" '
            f'image_count="{image_count}" audio_count="{audio_count}">'
            "This media belonged to an earlier message and is not current input."
            "</historical_media>"
        )

    def _compact_historical_message(self, message: ModelInputMessage) -> ModelInputMessage:
        parts = []
        image_count = audio_count = 0
        for part in message.parts:
            if isinstance(part, ModelImagePart):
                image_count += 1
            elif isinstance(part, ModelAudioPart):
                audio_count += 1
            else:
                parts.append(part)
        if image_count or audio_count:
            parts.append(
                self._historical_media_placeholder(image_count=image_count, audio_count=audio_count)
            )
        return replace(message, parts=tuple(parts))

    def _prepare_base_input(self, model_input: ModelInput, *, current_input_id: str) -> ModelInput:
        items = []
        for item in model_input.items:
            if self._is_runtime_context_item(item):
                continue
            if isinstance(item, ModelInputMessage) and item.id != current_input_id:
                item = self._compact_historical_message(item)
            items.append(item)
        return replace(model_input, items=tuple(items))

    def _with_system_prompt(self, model_input: ModelInput, *, system_prompt: str) -> ModelInput:
        items = tuple(
            item
            for item in model_input.items
            if not (isinstance(item, ModelInputMessage) and item.role == ModelRole.SYSTEM)
        )
        message = ModelInputMessage(
            id=self.SYSTEM_MESSAGE_ID, role=ModelRole.SYSTEM, parts=(ModelTextPart(system_prompt),)
        )
        return replace(model_input, items=(message, *items))

    def _inject_runtime_context(
        self,
        model_input: ModelInput,
        *,
        input_id: str,
        runtime_context: str,
        contributions: tuple[ContextContribution, ...] = (),
        query_scope: str = "",
    ) -> ModelInput:
        names = [item.name for item in contributions]
        if len(set(names)) != len(names):
            raise ValueError("Context contribution names must be unique")
        sections = [runtime_context.strip()] if runtime_context.strip() else []
        sections.extend(
            f"<{item.name}>\n{escape(item.content)}\n</{item.name}>" for item in contributions
        )
        if not sections:
            return model_input

        positions = [
            index
            for index, item in enumerate(model_input.items)
            if isinstance(item, ModelInputMessage) and item.id == input_id
        ]
        if len(positions) != 1:
            raise ValueError("Runtime context requires exactly one current input message")

        seed = json.dumps([query_scope, input_id], ensure_ascii=False, separators=(",", ":"))
        call_id = f"alphaavatar_runtime_{hashlib.sha256(seed.encode()).hexdigest()[:32]}"
        call = ModelFunctionCall(
            id=call_id,
            call_id=call_id,
            name=RUNTIME_CONTEXT_TOOL_NAME,
            arguments='{"source":"alphaavatar","scope":"current_query_only"}',
            metadata=MappingProxyType({"alphaavatar_runtime_context": True}),
        )
        output = ModelFunctionOutput(
            id=f"{call_id}:result",
            call_id=call_id,
            name=RUNTIME_CONTEXT_TOOL_NAME,
            parts=(ModelTextPart("\n\n".join(sections)),),
            is_error=False,
        )
        index = positions[0] + 1

        return replace(
            model_input,
            items=(*model_input.items[:index], call, output, *model_input.items[index:]),
        )

    def build(
        self,
        *,
        request: ContextBuildRequest,
        system_prompt: str,
        runtime_context: str,
        contributions: tuple[ContextContribution, ...] = (),
        query_scope: str = "",
    ) -> ContextBuildResult:
        from alphaavatar.agents.avatar.context.schemas import ContextBuildResult

        base = self._prepare_base_input(request.base_input, current_input_id=request.input_id)
        base = self._with_system_prompt(base, system_prompt=system_prompt)
        rendered = (
            self._renderers()
            .resolve(request.model_input_type)
            .render(replace(request, base_input=base))
        )
        model_input = self._inject_runtime_context(
            rendered.model_input,
            input_id=request.input_id,
            runtime_context=runtime_context,
            contributions=contributions,
            query_scope=query_scope,
        )

        return ContextBuildResult(model_input=model_input)
