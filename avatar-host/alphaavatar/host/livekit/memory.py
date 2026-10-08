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

import logging
from typing import TYPE_CHECKING

from livekit.agents import AgentSession, ConversationItemAddedEvent, FunctionToolsExecutedEvent, llm

from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelTextPart,
)

if TYPE_CHECKING:
    from alphaavatar.agents.entrypoints.livekit import LiveKitModelInput
    from alphaavatar.agents.memory import MemoryBase

logger = logging.getLogger(__name__)


class LiveKitMemoryBridge:
    """Temporary SDK event adapter. Memory only sees native records and owns no SDK state."""

    def __init__(self, *, memory: MemoryBase, adapter: LiveKitModelInput) -> None:
        self._memory = memory
        self._adapter = adapter
        self._session: AgentSession | None = None
        self._context_id: str | None = None
        self._closed = False
        self._error: Exception | None = None

    def start(self, session: AgentSession) -> None:
        if self._closed:
            raise RuntimeError("Memory bridge is closed")
        if self._session is not None:
            if self._session is not session:
                raise RuntimeError("Memory bridge is already bound to another session")
            return
        # Capture ownership once, never attribute a late event using mutable current State.
        self._context_id = self._memory.root_context_id
        session.on("conversation_item_added", self._on_message)
        try:
            session.on("function_tools_executed", self._on_tools)
        except BaseException:
            session.off("conversation_item_added", self._on_message)
            raise
        self._session = session

    def _failed(self, event: str, error: Exception) -> None:
        if self._error is None:
            self._error = error
        logger.error("Memory bridge rejected event=%s error_type=%s", event, type(error).__name__)

    def _on_message(self, event: ConversationItemAddedEvent) -> None:
        if self._closed or self._session is None:
            return
        try:
            if not isinstance(event.item, llm.ChatMessage) or event.item.role != "assistant":
                return
            items = self._adapter.from_chat_context(llm.ChatContext(items=[event.item])).items
            self._memory.add_messages(context_id=self._context_id, items=items)
        except Exception as exc:
            # SDK event callbacks cannot acknowledge async writes. Surface failure again at close.
            self._failed("conversation_item_added", exc)

    def _on_tools(self, event: FunctionToolsExecutedEvent) -> None:
        if self._closed or self._session is None:
            return
        try:
            items = []
            for call, output in zip(event.function_calls, event.function_call_outputs, strict=True):
                items.append(
                    ModelFunctionCall(
                        id=call.id,
                        call_id=call.call_id,
                        name=call.name,
                        arguments=call.arguments,
                        created_at=call.created_at,
                    )
                )
                # In Agents 1.4, StopResponse/handoff may yield no output. Do not invent success.
                if output is None:
                    continue
                if output.call_id != call.call_id or (output.name and output.name != call.name):
                    raise ValueError("SDK tool result does not match its call")
                items.append(
                    ModelFunctionOutput(
                        id=output.id,
                        call_id=call.call_id,
                        name=call.name,
                        parts=(ModelTextPart(output.output),),
                        is_error=output.is_error,
                        created_at=output.created_at,
                    )
                )
            self._memory.add_messages(context_id=self._context_id, items=items)
        except Exception as exc:
            self._failed("function_tools_executed", exc)

    def close(self) -> None:
        self._closed = True
        session, self._session = self._session, None
        if session is not None:
            for event, callback in (
                ("conversation_item_added", self._on_message),
                ("function_tools_executed", self._on_tools),
            ):
                try:
                    session.off(event, callback)
                except Exception as exc:
                    self._failed("unsubscribe", exc)
        if self._error is not None:
            raise RuntimeError(
                "SDK Memory ingestion failed; records may be incomplete"
            ) from self._error
