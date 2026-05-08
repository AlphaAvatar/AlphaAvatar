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
import re
import uuid
from dataclasses import dataclass

from livekit.agents import llm

from .enum.injection_mode import RuntimeContextInjectionMode
from .internal_tools import RUNTIME_CONTEXT_TOOL_NAME
from .prompts.runtime_context_prompts import (
    RUNTIME_CONTEXT_BEGIN,
    RUNTIME_CONTEXT_END,
)


@dataclass
class PromptAssembler:
    """
    Inject runtime context into ChatContext.

    Preferred mode:
        SYNTHETIC_TOOL

    Fallback mode:
        USER_APPEND

    Notes:
        In AlphaAvatar's current LiveKit flow, llm_node receives a temporary copied
        chat_ctx. Therefore injection here should not permanently pollute the agent's
        long-term chat context.
    """

    injection_mode: RuntimeContextInjectionMode = RuntimeContextInjectionMode.SYNTHETIC_TOOL
    runtime_tool_name: str = RUNTIME_CONTEXT_TOOL_NAME

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

        # Extra defensive check in case provider / LiveKit version stores metadata.
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

        This makes injection idempotent if llm_node is called multiple times because
        of retries, interruptions, or regeneration.
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
        Inject runtime context as a synthetic function call and function output.

        Resulting order:

            user message
            FunctionCall(name="alphaavatar_runtime_context")
            FunctionCallOutput(output="<alphaavatar_runtime_context>...</...>")
            assistant answer

        This keeps raw user query clean while giving the model a standard tool-result
        shaped context block.
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
        chat_ctx.items[insert_at:insert_at] = [
            function_call,
            function_output,
        ]

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
