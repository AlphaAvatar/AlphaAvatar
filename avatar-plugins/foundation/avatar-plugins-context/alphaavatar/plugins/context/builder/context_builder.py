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
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelInput,
    ModelInputMessage,
    ModelTextPart,
)
from alphaavatar.agents.constants import RUNTIME_CONTEXT_TOOL_NAME
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnSnapshot

from .renderer.history import compact_historical_message
from .renderer.notice import render_system_notice
from .renderer.op import replace_current

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

    def _prepare_base_input(self, model_input: ModelInput, *, current_input_id: str) -> ModelInput:
        items = []
        for item in model_input.items:
            if self._is_runtime_context_item(item):
                continue
            if isinstance(item, ModelInputMessage) and item.id != current_input_id:
                item = compact_historical_message(item)
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
        snapshot: TurnSnapshot,
        system_prompt: str,
        runtime_context: str,
        contributions: tuple[ContextContribution, ...] = (),
        query_scope: str = "",
    ) -> ContextBuildResult:
        from alphaavatar.agents.avatar.context.schemas import ContextBuildResult

        base = self._prepare_base_input(request.base_input, current_input_id=request.input_id)
        base = self._with_system_prompt(base, system_prompt=system_prompt)
        notice = render_system_notice(snapshot, current=True)
        if notice is not None and snapshot.modality == TurnInputModality.SYSTEM:
            rendered = replace_current(base, request.input_id, (notice,))
        else:
            rendered = (
                self._renderers()
                .resolve(request.model_input_type)
                .render(replace(request, base_input=base))
                .model_input
            )
            if notice is not None:
                current = rendered.get(request.input_id)
                parts = current.parts if isinstance(current, ModelInputMessage) else ()
                rendered = replace_current(rendered, request.input_id, (*parts, notice))

        model_input = self._inject_runtime_context(
            rendered,
            input_id=request.input_id,
            runtime_context=runtime_context,
            contributions=contributions,
            query_scope=query_scope,
        )

        return ContextBuildResult(model_input=model_input)
