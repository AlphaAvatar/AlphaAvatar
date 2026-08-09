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

import json
from dataclasses import replace
from types import MappingProxyType
from uuid import uuid4

from alphaavatar.agents.constants import RUNTIME_CONTEXT_TOOL_NAME
from alphaavatar.agents.providers.schema import (
    ModelAudioPart,
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelImagePart,
    ModelInput,
    ModelInputMessage,
    ModelInputType,
    ModelRole,
    ModelTextPart,
)

from .renderer import (
    PromptRendererRegistry,
    PromptRenderRequest,
    PromptRenderResult,
    RealtimeRenderer,
    TextRenderer,
    VLMRenderer,
)


class PromptManager:
    """
    Build one temporary model-facing input.

    Responsibilities:
    - remove stale runtime-context items;
    - compact historical media;
    - replace the system prompt;
    - render the current user turn;
    - inject fresh runtime context as a synthetic function call/output pair.

    Persistent conversation history is never mutated.
    """

    SYSTEM_MESSAGE_ID = "alphaavatar.system"

    def __init__(
        self,
        registry: PromptRendererRegistry | None = None,
    ) -> None:
        self._registry = registry or PromptRendererRegistry()

        if registry is None:
            self._registry.register(
                input_type=ModelInputType.TEXT,
                renderer=TextRenderer(),
            )
            self._registry.register(
                input_type=ModelInputType.VLM,
                renderer=VLMRenderer(),
            )
            self._registry.register(
                input_type=ModelInputType.REALTIME,
                renderer=RealtimeRenderer(),
            )

    @staticmethod
    def _is_runtime_context_item(item: object) -> bool:
        return (
            isinstance(item, ModelFunctionCall | ModelFunctionOutput)
            and item.name == RUNTIME_CONTEXT_TOOL_NAME
        )

    @staticmethod
    def _historical_media_placeholder(
        *,
        image_count: int,
        audio_count: int,
    ) -> ModelTextPart:
        return ModelTextPart(
            "<historical_media "
            'omitted="true" '
            'current="false" '
            f'image_count="{image_count}" '
            f'audio_count="{audio_count}">'
            "This media belonged to an earlier message and is not current input."
            "</historical_media>"
        )

    def _compact_historical_message(
        self,
        message: ModelInputMessage,
    ) -> ModelInputMessage:
        parts = []
        image_count = 0
        audio_count = 0

        for part in message.parts:
            if isinstance(part, ModelImagePart):
                image_count += 1
                continue

            if isinstance(part, ModelAudioPart):
                audio_count += 1
                continue

            parts.append(part)

        if image_count or audio_count:
            parts.append(
                self._historical_media_placeholder(
                    image_count=image_count,
                    audio_count=audio_count,
                )
            )

        return replace(message, parts=tuple(parts))

    def _prepare_base_input(
        self,
        model_input: ModelInput,
        *,
        current_input_id: str,
    ) -> ModelInput:
        items = []

        for item in model_input.items:
            # Runtime context is current-answer-only and must be rebuilt for
            # every model invocation, including retries and post-tool calls.
            if self._is_runtime_context_item(item):
                continue

            if isinstance(item, ModelInputMessage) and item.id != current_input_id:
                item = self._compact_historical_message(item)

            items.append(item)

        return replace(model_input, items=tuple(items))

    def _with_system_prompt(
        self,
        model_input: ModelInput,
        *,
        system_prompt: str,
    ) -> ModelInput:
        items = tuple(
            item
            for item in model_input.items
            if not (isinstance(item, ModelInputMessage) and item.role == ModelRole.SYSTEM)
        )

        system_message = ModelInputMessage(
            id=self.SYSTEM_MESSAGE_ID,
            role=ModelRole.SYSTEM,
            parts=(ModelTextPart(system_prompt),),
        )

        return replace(
            model_input,
            items=(system_message, *items),
        )

    def _inject_runtime_context(
        self,
        model_input: ModelInput,
        *,
        input_id: str,
        runtime_context: str,
    ) -> ModelInput:
        runtime_context = runtime_context.strip()

        if not runtime_context:
            return model_input

        call_id = f"alphaavatar_runtime_{uuid4().hex}"

        function_call = ModelFunctionCall(
            id=call_id,
            call_id=call_id,
            name=RUNTIME_CONTEXT_TOOL_NAME,
            arguments=json.dumps(
                {
                    "source": "alphaavatar",
                    "scope": "current_answer_only",
                },
                ensure_ascii=False,
            ),
            metadata=MappingProxyType(
                {
                    "alphaavatar_runtime_context": True,
                }
            ),
        )

        function_output = ModelFunctionOutput(
            id=call_id,
            call_id=call_id,
            name=RUNTIME_CONTEXT_TOOL_NAME,
            output=runtime_context,
            is_error=False,
        )

        items = list(model_input.items)
        insert_at = len(items)

        for index, item in enumerate(items):
            if isinstance(item, ModelInputMessage) and item.id == input_id:
                insert_at = index + 1
                break

        items[insert_at:insert_at] = [
            function_call,
            function_output,
        ]

        return replace(model_input, items=tuple(items))

    def render(
        self,
        *,
        request: PromptRenderRequest,
        system_prompt: str,
        runtime_context: str,
    ) -> PromptRenderResult:
        base_input = self._prepare_base_input(
            request.base_input,
            current_input_id=request.input_id,
        )
        base_input = self._with_system_prompt(
            base_input,
            system_prompt=system_prompt,
        )

        renderer = self._registry.resolve(request.model_input_type)
        rendered = renderer.render(
            replace(
                request,
                base_input=base_input,
            )
        )

        return PromptRenderResult(
            model_input=self._inject_runtime_context(
                rendered.model_input,
                input_id=request.input_id,
                runtime_context=runtime_context,
            )
        )
