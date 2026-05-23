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
"""
PromptAssembler builds temporary model-facing ChatContext objects.

It should not mutate persistent session history except for explicitly requested
runtime-context injection on temporary contexts.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass

from livekit.agents import llm

from alphaavatar.agents.avatar.vision.constants import (
    HISTORICAL_VISUAL_PLACEHOLDER_PREFIX,
    LATEST_VIDEO_FRAME_LABEL,
    VIDEO_FRAME_LABEL_PREFIX,
    VISUAL_INPUT_PREFIX,
)

from ..context.internal_tools import RUNTIME_CONTEXT_TOOL_NAME
from .enum.injection_mode import RuntimeContextInjectionMode
from .prompts.runtime_context_prompts import (
    RUNTIME_CONTEXT_BEGIN,
    RUNTIME_CONTEXT_END,
)


@dataclass
class PromptAssembler:
    """
    Build model-facing ChatContext objects and inject runtime context.

    Design:
    - persistent chat_ctx may keep full raw history
    - model-facing chat_ctx should be compacted before LLM inference
    - runtime context injection should be idempotent
    """

    injection_mode: RuntimeContextInjectionMode = RuntimeContextInjectionMode.SYNTHETIC_TOOL
    runtime_tool_name: str = RUNTIME_CONTEXT_TOOL_NAME

    # -------------------------------------------------------------------------
    # Runtime context injection
    # -------------------------------------------------------------------------

    def inject_runtime_context(
        self,
        chat_ctx: llm.ChatContext,
        *,
        runtime_context: str,
    ) -> llm.ChatContext:
        if not runtime_context or not runtime_context.strip():
            return chat_ctx

        if self.injection_mode == RuntimeContextInjectionMode.SYNTHETIC_TOOL:
            return self._inject_as_synthetic_tool(
                chat_ctx,
                runtime_context=runtime_context,
            )

        if self.injection_mode == RuntimeContextInjectionMode.USER_APPEND:
            return self._inject_as_user_append(
                chat_ctx,
                runtime_context=runtime_context,
            )

        return self._inject_as_user_append(
            chat_ctx,
            runtime_context=runtime_context,
        )

    def _strip_existing_runtime_context_text(self, text: str) -> str:
        """
        Remove an existing AlphaAvatar runtime context block from text.

        Used by USER_APPEND fallback.
        """
        if not text:
            return ""

        pattern = re.escape(RUNTIME_CONTEXT_BEGIN) + r".*?" + re.escape(RUNTIME_CONTEXT_END)
        return re.sub(pattern, "", text, flags=re.DOTALL).strip()

    def _is_runtime_context_function_item(self, item: object) -> bool:
        """
        Detect synthetic AlphaAvatar runtime context function call/output items.
        """
        item_name = getattr(item, "name", None)
        if item_name == self.runtime_tool_name:
            return True

        extra = getattr(item, "extra", None)
        if isinstance(extra, dict) and extra.get("alphaavatar_runtime_context") is True:
            return True

        return False

    def _remove_existing_runtime_context_items(
        self,
        chat_ctx: llm.ChatContext,
    ) -> None:
        """
        Remove previously injected runtime context function call/output items.

        This makes injection idempotent for retries, interruptions, and regeneration.
        """
        chat_ctx.items[:] = [
            item for item in chat_ctx.items if not self._is_runtime_context_function_item(item)
        ]

    def _find_latest_user_index(self, chat_ctx: llm.ChatContext) -> int | None:
        for idx in range(len(chat_ctx.items) - 1, -1, -1):
            item = chat_ctx.items[idx]
            if isinstance(item, llm.ChatMessage) and item.role == "user":
                return idx
        return None

    def _inject_as_synthetic_tool(
        self,
        chat_ctx: llm.ChatContext,
        *,
        runtime_context: str,
    ) -> llm.ChatContext:
        """
        Inject runtime context as a synthetic function call and output.

        Resulting order:
            user message
            FunctionCall(name="alphaavatar_runtime_context")
            FunctionCallOutput(output="<alphaavatar_runtime_context>...</...>")
            assistant answer
        """
        self._remove_existing_runtime_context_items(chat_ctx)

        latest_user_idx = self._find_latest_user_index(chat_ctx)
        if latest_user_idx is None:
            return chat_ctx

        call_id = f"alphaavatar_runtime_{uuid.uuid4().hex}"

        function_call = llm.FunctionCall(
            id=call_id,
            call_id=call_id,
            name=self.runtime_tool_name,
            arguments=json.dumps(
                {
                    "source": "alphaavatar",
                    "scope": "current_answer_only",
                },
                ensure_ascii=False,
            ),
        )

        function_output = llm.FunctionCallOutput(
            id=call_id,
            call_id=call_id,
            name=self.runtime_tool_name,
            output=runtime_context,
            is_error=False,
        )

        insert_at = latest_user_idx + 1
        chat_ctx.items[insert_at:insert_at] = [function_call, function_output]
        return chat_ctx

    def _inject_as_user_append(
        self,
        chat_ctx: llm.ChatContext,
        *,
        runtime_context: str,
    ) -> llm.ChatContext:
        """
        Most compatible fallback.

        Appends runtime context to the latest user message with XML isolation.
        """
        for item in reversed(chat_ctx.items):
            if isinstance(item, llm.ChatMessage) and item.role == "user":
                original_text = item.text_content or ""
                original_text = self._strip_existing_runtime_context_text(original_text)
                injected_text = f"{original_text}\n\n{runtime_context}"

                try:
                    item.content = [injected_text]
                except Exception:
                    item.content = injected_text

                return chat_ctx

        return chat_ctx

    # -------------------------------------------------------------------------
    # Model-facing context compaction
    # -------------------------------------------------------------------------

    def prepare_model_chat_context(
        self,
        chat_ctx: llm.ChatContext,
        *,
        strip_historical_visuals: bool = True,
        add_visual_placeholder: bool = True,
    ) -> llm.ChatContext:
        """
        Create a temporary model-facing ChatContext.

        Original chat_ctx is not modified.

        Intended flow:
            model_chat_ctx = prepare_model_chat_context(chat_ctx)
            vision.inject_into_chat_ctx(model_chat_ctx)
            inject_runtime_context(model_chat_ctx, ...)
            call LLM
        """
        model_chat_ctx = self._shallow_clone_chat_context(chat_ctx)

        new_items: list[object] = []

        for item in chat_ctx.items:
            if not isinstance(item, llm.ChatMessage):
                new_items.append(item)
                continue

            cloned_item = copy.copy(item)

            if strip_historical_visuals:
                cloned_item.content = self._strip_visual_content_parts(
                    getattr(item, "content", None),
                    add_placeholder=add_visual_placeholder,
                )

            new_items.append(cloned_item)

        model_chat_ctx.items = new_items
        return model_chat_ctx

    def _shallow_clone_chat_context(self, chat_ctx: llm.ChatContext) -> llm.ChatContext:
        """
        Clone ChatContext without deep-copying heavy multimodal payloads.
        """
        try:
            return chat_ctx.copy()
        except Exception:
            return copy.copy(chat_ctx)

    def _is_visual_content_part(self, part: object) -> bool:
        """
        Detect LiveKit visual payload parts.

        String markers are not enough; ImageContent must also be removed.
        """
        if getattr(part, "type", None) == "image_content":
            return True

        if part.__class__.__name__ == "ImageContent":
            return True

        return False

    def _is_visual_marker_text(self, text: str) -> bool:
        stripped = text.strip()

        if VISUAL_INPUT_PREFIX in stripped:
            return True

        if stripped.startswith(VIDEO_FRAME_LABEL_PREFIX):
            return True

        if stripped == LATEST_VIDEO_FRAME_LABEL:
            return True

        if stripped.startswith(HISTORICAL_VISUAL_PLACEHOLDER_PREFIX):
            return True

        return False

    def _strip_visual_content_parts(
        self,
        content: object,
        *,
        add_placeholder: bool = True,
    ) -> object:
        """
        Remove visual payloads and AlphaAvatar visual marker strings.

        Keeps normal user/assistant text.
        """
        if isinstance(content, str):
            if self._is_visual_marker_text(content):
                return ""
            return content

        if not isinstance(content, list):
            return content

        new_content: list[object] = []
        removed_frames = 0

        for part in content:
            if self._is_visual_content_part(part):
                removed_frames += 1
                continue

            if isinstance(part, str) and self._is_visual_marker_text(part):
                continue

            new_content.append(part)

        if removed_frames and add_placeholder:
            new_content.append(
                f"{HISTORICAL_VISUAL_PLACEHOLDER_PREFIX} "
                f"{removed_frames} frame(s) were attached in the original turn.]"
            )

        return new_content
