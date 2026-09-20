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

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from livekit.agents.llm import ChatItem, ChatMessage, FunctionCall, FunctionCallOutput

from alphaavatar.agents.memory import MemoryProcessorBase
from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.memory.schemas import (
    MemoryCheckpointAdvance,
    MemoryItem,
    MemoryOwnerRef,
    MemoryParticipantRef,
    MemoryScope,
    MemorySourceRef,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.utils.time import application_now
from alphaavatar.core.turn import TurnSnapshot

from ..schemas import norm_token, norm_topic
from ..storage.graph import build_graph_from_mentions
from ..template import MemoryPluginsTemplate

if TYPE_CHECKING:
    from ..runtime import MemoryRuntime
    from ..schemas import PatchOp
    from ..state import MemoryContextItem, MemoryContextState
    from ..storage import MemoryStore


class MemoryProcessor(MemoryProcessorBase):
    def __init__(self, *, runtime: AvatarRuntime, memory: MemoryRuntime) -> None:
        super().__init__(runtime=runtime, memory=memory)
        self._memory_runtime = memory

    @property
    def memory_runtime(self) -> MemoryRuntime:
        return self._memory_runtime

    @property
    def store(self) -> MemoryStore:
        return self._memory_runtime.store

    @property
    def avatar_id(self) -> str:
        return self._memory_runtime.avatar_id

    @staticmethod
    def deduplicate_refs(refs: Iterable) -> list:
        return list({ref.key: ref for ref in refs}.values())

    @classmethod
    def source_refs(cls, messages: list[MemoryContextItem]) -> list[MemorySourceRef]:
        refs = []

        for item in messages:
            if isinstance(item, TurnSnapshot):
                refs.append(MemorySourceRef.message(item.input_id))
                continue

            if isinstance(item, ChatMessage):
                if source_id := str(getattr(item, "id", "") or "").strip():
                    refs.append(MemorySourceRef.message(source_id))
                continue

            call_id = str(getattr(item, "call_id", "") or getattr(item, "id", "") or "").strip()
            tool_id = str(getattr(item, "name", "") or "").strip()

            if call_id and tool_id:
                if isinstance(item, FunctionCall):
                    refs.append(MemorySourceRef.tool_call(tool_id, call_id))
                elif isinstance(item, FunctionCallOutput):
                    refs.append(MemorySourceRef.tool_result(tool_id, call_id))

        return cls.deduplicate_refs(refs)

    def build_memory_items(
        self,
        *,
        state: MemoryContextState,
        memory_type: MemoryType,
        patches: list[PatchOp],
        owner_refs: list[MemoryOwnerRef],
        participant_refs: list[MemoryParticipantRef],
        source_refs: list[MemorySourceRef],
        scope: MemoryScope,
        extra_data: dict[str, Any] | None = None,
    ) -> list[MemoryItem]:
        created_at = application_now()
        items: list[MemoryItem] = []

        for patch in patches:
            if not norm_token(patch.value):
                continue

            item = MemoryItem(
                context=state.context,
                scope=scope,
                owner_refs=owner_refs,
                participant_refs=participant_refs,
                source_refs=source_refs,
                value=patch.value,
                topic=norm_topic(patch.topic),
                created_at=created_at,
                memory_type=memory_type,
                extra_data=dict(extra_data or {}),
            )
            item.graph_nodes, item.graph_links = build_graph_from_mentions(
                item=item,
                mentions=patch.node_mentions,
            )
            items.append(item)

        return items

    def trace_metadata(
        self,
        *,
        state: MemoryContextState,
        component: str,
        operation: str,
        memory_type: MemoryType,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = state.context

        metadata = {
            "provider_dir": str(state.provider_dir),
            "plugin": "memory",
            "component": component,
            "operation": operation,
            "episode_id": context.episode_id,
            "context_id": context.context_id,
            "session_id": context.session_id,
            "cache_type": state.cache_type.value,
            "memory_type": memory_type.value,
        }

        if extra:
            metadata.update(extra)

        return metadata

    def render_context_content(
        self,
        state: MemoryContextState,
        messages: list[ChatItem],
    ) -> str:
        content = MemoryPluginsTemplate.apply_update_template(
            messages,
            state.cache_type,
        )
        env_memory = self.memory_runtime.memory_state.render(
            memory_type=MemoryType.ENV,
            context_id=state.context_id,
        )

        if not env_memory:
            return content

        return "\n\n".join(
            (
                content,
                "[CURRENT CONTEXT ENV MEMORY]",
                env_memory,
                "[END CURRENT CONTEXT ENV MEMORY]",
            )
        )

    async def checkpoint_window(
        self,
        state: MemoryContextState,
    ) -> tuple[int, int, list[ChatItem]]:
        start = await self.store.get_checkpoint(context_id=state.context_id, processor=self.name)
        end = state.message_sequence

        if start > end:
            raise RuntimeError(
                f"Memory checkpoint exceeds context sequence: "
                f"{state.context_id}:{self.name} checkpoint={start} messages={end}"
            )

        return start, end, state.messages_between(start, end)

    async def commit_items(
        self,
        *,
        state: MemoryContextState,
        start: int,
        end: int,
        items: list[MemoryItem],
    ) -> None:
        await self.store.commit(
            items,
            context_id=state.context_id,
            processor=self.name,
            idempotency_key=f"{state.context_id}:{self.name}:{start}:{end}",
            checkpoint=MemoryCheckpointAdvance(from_sequence=start, to_sequence=end),
        )
        self.memory_runtime.apply_items(items)

    async def _start(self) -> None: ...

    async def _stop(self, *, finalize: bool) -> None: ...
