# Copyright 2025 AlphaAvatar project
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

import pathlib
from abc import abstractmethod
from typing import Any

from livekit.agents.llm import ChatItem

from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.agents.runtime import AvatarRuntime, ContextRuntime, SessionRuntime
from alphaavatar.agents.runtime.capability import (
    AvatarCapability,
    AvatarCapabilityName,
    avatar_capability,
)
from alphaavatar.core.perception import PerceptionRuntime

from .context_state import MemoryContextState
from .enums import MemoryCacheType, MemoryType
from .memory_state import MemoryState
from .schemas import (
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryParticipantRef,
)


@avatar_capability(
    name=AvatarCapabilityName.MEMORY_CONVERSATION,
    description="Can retain and recall relevant information learned from conversations across sessions.",
)
@avatar_capability(
    name=AvatarCapabilityName.MEMORY_ENVIRONMENT,
    description=(
        "Can form and recall persistent memories from relevant visual, audio, "
        "and environmental observations when such perception is available."
    ),
)
@avatar_capability(
    name=AvatarCapabilityName.MEMORY_TOOL,
    description="Can retain and recall useful information from previous tool interactions and results.",
)
@avatar_capability(
    name=AvatarCapabilityName.MEMORY_GRAPH,
    description=(
        "Can connect and retrieve related memories through entities, aliases, "
        "and graph relationships."
    ),
)
class MemoryBase(AvatarRuntimePlugin):
    capabilities: tuple[AvatarCapability, ...]

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        avatar_id: str,
        memory_search_context: int = 3,
        memory_recall_num: int = 10,
        maximum_memory_num: int = 24,
    ) -> None:
        super().__init__()
        self.runtime = runtime
        self.avatar_id = avatar_id
        self._memory_search_context = memory_search_context
        self._memory_recall_num = memory_recall_num
        self._memory_contexts: dict[str, MemoryContextState] = {}
        self._memory_state = MemoryState(maximum_memory_num=maximum_memory_num)
        self._root_context_id: str | None = None

    @property
    def session_runtime(self) -> SessionRuntime:
        return self.runtime.session

    @property
    def context_runtime(self) -> ContextRuntime:
        return self.runtime.context

    @property
    def perception_runtime(self) -> PerceptionRuntime:
        return self.runtime.perception

    @property
    def memory_search_context(self) -> int:
        return self._memory_search_context

    @property
    def memory_recall_num(self) -> int:
        return self._memory_recall_num

    @property
    def memory_contexts(self) -> dict[str, MemoryContextState]:
        return self._memory_contexts

    @property
    def root_context_id(self) -> str:
        if self._root_context_id is None:
            raise RuntimeError("Memory root context is not initialized")
        return self._root_context_id

    @property
    def memory_state(self) -> MemoryState:
        return self._memory_state

    @property
    def avatar_memory(self) -> str:
        return self._memory_state.render(memory_type=MemoryType.Avatar)

    @property
    def user_memory(self) -> str:
        return self._memory_state.render(memory_type=MemoryType.CONVERSATION)

    @property
    def tool_memory(self) -> str:
        return self._memory_state.render(memory_type=MemoryType.TOOLS)

    @property
    def env_memory(self) -> str:
        return self._memory_state.render(memory_type=MemoryType.ENV)

    @property
    def memory_content(self) -> str:
        return "\n".join(
            filter(None, (self.avatar_memory, self.user_memory, self.tool_memory, self.env_memory))
        )

    @property
    def memory_items(self) -> list[MemoryItem]:
        return self._memory_state.all_items

    @avatar_memory.setter
    def avatar_memory(self, items: list[MemoryItem]) -> None:
        self._memory_state.add(MemoryType.Avatar, items)

    @user_memory.setter
    def user_memory(self, items: list[MemoryItem]) -> None:
        self._memory_state.add(MemoryType.CONVERSATION, items)

    @tool_memory.setter
    def tool_memory(self, items: list[MemoryItem]) -> None:
        self._memory_state.add(MemoryType.TOOLS, items)

    @env_memory.setter
    def env_memory(self, items: list[MemoryItem]) -> None:
        self._memory_state.add(MemoryType.ENV, items)

    def _get_context_state_or_raise(self, context_id: str) -> MemoryContextState:
        state = self._memory_contexts.get(context_id)
        if state is None:
            raise ValueError(f"Memory context not found: {context_id}")
        return state

    def _sync_user_refs(self) -> None:
        for migration in self.session_runtime.pending_user_path_migrations:
            for state in self._memory_contexts.values():
                state.replace_user_id(migration.old_user_id, migration.new_user_id)

    def open_context(
        self,
        *,
        context: MemoryContextRef,
        provider_dir: pathlib.Path,
        owner_refs: list[MemoryOwnerRef],
        participant_refs: list[MemoryParticipantRef] | None = None,
        cache_type: MemoryCacheType = MemoryCacheType.SESSION_INTERACTION,
    ) -> MemoryContextState:
        if context.context_id in self._memory_contexts:
            raise ValueError(f"Memory context already exists: {context.context_id}")

        if context.parent_context_id:
            parent = self._get_context_state_or_raise(context.parent_context_id)
            if parent.context.conversation_id != context.conversation_id:
                raise ValueError("Parent and child memory contexts must share conversation_id")

        state = MemoryContextState(
            context=context,
            provider_dir=provider_dir,
            owner_refs=owner_refs,
            participant_refs=participant_refs,
            cache_type=cache_type,
        )
        self._memory_contexts[context.context_id] = state
        return state

    def close_context(self, context_id: str) -> MemoryContextState:
        state = self._get_context_state_or_raise(context_id)
        if any(
            item.context.parent_context_id == context_id for item in self._memory_contexts.values()
        ):
            raise RuntimeError(f"Memory context has open children: {context_id}")

        del self._memory_contexts[context_id]
        if self._root_context_id == context_id:
            self._root_context_id = None
        return state

    def add_message(self, *, context_id: str, chat_item: ChatItem) -> None:
        state = self._get_context_state_or_raise(context_id)
        state.add_message(chat_item)
        self._sync_user_refs()
        self.on_context_message_added(context_id=context_id, chat_item=chat_item)

    @abstractmethod
    def on_context_message_added(self, *, context_id: str, chat_item: ChatItem) -> None: ...

    @abstractmethod
    def save_graph_aliases(self, aliases: list[dict[str, Any]]) -> dict[str, Any]: ...

    @abstractmethod
    async def search_by_context(
        self,
        *,
        context_id: str,
        chat_context: list[ChatItem],
    ) -> None: ...

    @abstractmethod
    async def search_by_graph_node(
        self,
        *,
        node_key: str | None = None,
        node_query: str | None = None,
        context_id: str | None = None,
        memory_type: MemoryType | None = None,
        node_type: str | None = None,
        max_hops: int = 0,
        top_k: int = 50,
        timeout: float = 3.0,
    ) -> list[MemoryItem]: ...

    @abstractmethod
    async def update(self, *, context_id: str | None = None) -> None: ...

    async def on_session_start(self) -> None:
        user_id = self.session_runtime.primary_user_id
        session_path = self.session_runtime.session_path
        if not user_id:
            return
        if session_path is None:
            raise RuntimeError("SessionRuntime.session_path is not initialized")

        session_id = self.session_runtime.session_id
        context = MemoryContextRef(
            conversation_id=session_id,
            context_id=session_id,
            session_id=session_id,
            created_at=self.session_runtime.created_at,
        )
        self.open_context(
            context=context,
            provider_dir=session_path.provider_dir,
            owner_refs=[MemoryOwnerRef.user(user_id)],
            participant_refs=[
                MemoryParticipantRef.user(user_id),
                MemoryParticipantRef.avatar(self.avatar_id),
            ],
        )
        self._root_context_id = context.context_id

    async def on_session_stop(self) -> None:
        await self.update()
