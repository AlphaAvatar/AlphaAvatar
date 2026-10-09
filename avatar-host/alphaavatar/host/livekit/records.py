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
from hashlib import sha256
from typing import TYPE_CHECKING

from livekit.agents import AgentSession, ConversationItemAddedEvent, FunctionToolsExecutedEvent, llm

from alphaavatar.agents.avatar.provider.records import model_record_batch
from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelTextPart,
)
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.output.schemas import OutputScope

if TYPE_CHECKING:
    from alphaavatar.agents.entrypoints.livekit import LiveKitModelInput

logger = logging.getLogger(__name__)


class LiveKitOutputBridge:
    """Temporary SDK-to-record adapter. It knows OutputRuntime, never a Memory instance."""

    def __init__(
        self,
        *,
        output: OutputRuntime,
        adapter: LiveKitModelInput,
        context_id: str,
    ) -> None:
        self._output, self._adapter = output, adapter
        # Legacy SDK events do not supply a native run/turn identity. Never guess the latest one.
        self._scope = OutputScope(context_id)
        self._session: AgentSession | None = None
        self._closed = False
        self._error: Exception | None = None

    def start(self, session: AgentSession) -> None:
        if self._closed:
            raise RuntimeError("Output bridge is closed")
        if self._session is not None:
            if self._session is not session:
                raise RuntimeError("Output bridge is already bound to another session")
            return
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
        logger.error("SDK output ingestion rejected event=%s error=%s", event, type(error).__name__)

    def _publish(self, items: tuple) -> None:
        # IDs are scoped by the immutable context captured at construction.
        identities = "\0".join((self._scope.context_id, *(item.id for item in items)))
        batch = model_record_batch(
            batch_id=f"livekit:{sha256(identities.encode()).hexdigest()}",
            source="livekit.sdk",
            scope=self._scope,
            items=items,
        )
        if batch is not None:
            self._output.publish_records(batch)

    def _on_message(self, event: ConversationItemAddedEvent) -> None:
        if self._closed or self._session is None:
            return
        try:
            if not isinstance(event.item, llm.ChatMessage) or event.item.role != "assistant":
                return
            items = self._adapter.from_chat_context(llm.ChatContext(items=[event.item])).items
            self._publish(items)
        except Exception as exc:
            self._failed("conversation_item_added", exc)

    def _on_tools(self, event: FunctionToolsExecutedEvent) -> None:
        if self._closed or self._session is None:
            return
        try:
            items = []
            for call, result in zip(event.function_calls, event.function_call_outputs, strict=True):
                items.append(
                    ModelFunctionCall(
                        id=call.id,
                        call_id=call.call_id,
                        name=call.name,
                        arguments=call.arguments,
                        created_at=call.created_at,
                    )
                )
                if result is None:
                    continue  # An SDK event with no result is not proof of successful execution.
                if result.call_id != call.call_id or (result.name and result.name != call.name):
                    raise ValueError("SDK tool result does not match its call")
                items.append(
                    ModelFunctionOutput(
                        id=result.id,
                        call_id=call.call_id,
                        name=call.name,
                        parts=(ModelTextPart(result.output),),
                        is_error=result.is_error,
                        created_at=result.created_at,
                    )
                )
            self._publish(tuple(items))
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
            raise RuntimeError("SDK output records were not fully accepted") from self._error
