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

import pathlib
from collections.abc import Sequence
from uuid import uuid4

from livekit.agents.llm import ChatItem

from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.memory.enums import MemoryCacheType, MemoryType
from alphaavatar.agents.memory.schemas import (
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryParticipantRef,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import AvatarCapabilityRegistry

from .processors.base import MemoryProcessor
from .state import MemoryContextState, MemoryState
from .storage import MemoryStore


class MemoryRuntime(MemoryBase):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        avatar_id: str,
        store: MemoryStore,
        maximum_memory_num: int = 24,
    ) -> None:
        self._runtime = runtime
        self._avatar_id = avatar_id
        self._store = store

        self._memory_contexts: dict[str, MemoryContextState] = {}
        self._memory_state = MemoryState(maximum_memory_num=maximum_memory_num)
        self._root_context_id: str | None = None

        self._processors: tuple[MemoryProcessor, ...] = ()
        self._processors_by_name: dict[str, MemoryProcessor] = {}
        self._started_processors: list[MemoryProcessor] = []
        self._processors_bound = False
        self._started = False

        self._capability_registry = AvatarCapabilityRegistry()

    @property
    def avatar_id(self) -> str:
        return self._avatar_id

    @property
    def store(self) -> MemoryStore:
        return self._store

    @property
    def capability_registry(self) -> AvatarCapabilityRegistry:
        return self._capability_registry

    @property
    def root_context_id(self) -> str:
        if self._root_context_id is None:
            raise RuntimeError("Memory root context is not initialized")
        return self._root_context_id

    @property
    def memory_contexts(self) -> dict[str, MemoryContextState]:
        return self._memory_contexts

    @property
    def memory_state(self) -> MemoryState:
        return self._memory_state

    @property
    def memory_content(self) -> str:
        return "\n".join(
            filter(
                None,
                (
                    self._memory_state.render(memory_type=MemoryType.Avatar),
                    self._memory_state.render(memory_type=MemoryType.CONVERSATION),
                    self._memory_state.render(memory_type=MemoryType.TOOLS),
                    self._memory_state.render(memory_type=MemoryType.ENV),
                ),
            )
        )

    def bind_processors(self, processors: Sequence[MemoryProcessor]) -> None:
        if self._processors_bound:
            raise RuntimeError("Memory processors have already been bound")
        if self._started:
            raise RuntimeError("Memory processors cannot be bound after runtime start")

        names = [processor.name for processor in processors]
        if len(names) != len(set(names)):
            raise ValueError(f"Memory processor names must be unique: {names}")

        registry = AvatarCapabilityRegistry(*processors)

        self._processors = tuple(processors)
        self._processors_by_name = {processor.name: processor for processor in processors}
        self._capability_registry = registry
        self._processors_bound = True

    def context_state(self, context_id: str) -> MemoryContextState:
        state = self._memory_contexts.get(context_id)
        if state is None:
            raise ValueError(f"Memory context not found: {context_id}")
        return state

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
        state = self.context_state(context_id)

        if any(
            item.context.parent_context_id == context_id for item in self._memory_contexts.values()
        ):
            raise RuntimeError(f"Memory context has open children: {context_id}")

        del self._memory_contexts[context_id]

        if self._root_context_id == context_id:
            self._root_context_id = None

        return state

    def _sync_user_refs(self) -> None:
        for migration in self._runtime.session.pending_user_path_migrations:
            for state in self._memory_contexts.values():
                state.replace_user_id(
                    migration.old_user_id,
                    migration.new_user_id,
                )

    def add_message(self, *, context_id: str, chat_item: ChatItem) -> None:
        state = self.context_state(context_id)
        state.add_message(chat_item)
        self._sync_user_refs()

        for processor in self._processors:
            processor.on_message(
                state=state,
                chat_item=chat_item,
            )

    def apply_items(self, items: list[MemoryItem]) -> None:
        superseded = {memory_id for item in items for memory_id in item.supersedes_memory_ids}

        if superseded:
            self._memory_state.discard(superseded)

        current = [item for item in items if item.memory_id not in superseded]

        for memory_type in MemoryType:
            bucket = [item for item in current if item.memory_type is memory_type]
            if bucket:
                self._memory_state.add(memory_type, bucket)

    # Temporary bridge until passive retrieval is moved to committed TurnSnapshot.
    async def search_by_context(
        self,
        *,
        context_id: str,
        chat_context: list[ChatItem],
        timeout: float = 3.0,
    ) -> None:
        processor = self._processors_by_name.get("retrieval")

        if processor is None:
            return

        await processor.search_context(
            context_id=context_id,
            chat_context=chat_context,
            timeout=timeout,
        )

    def _open_root_context(self) -> None:
        user_id = self._runtime.session.primary_user_id
        session_path = self._runtime.session.session_path

        if not user_id:
            return

        if session_path is None:
            raise RuntimeError("SessionRuntime.session_path is not initialized")

        context = MemoryContextRef(
            episode_id=uuid4().hex,
            context_id=uuid4().hex,
            session_id=self._runtime.session.session_id,
            created_at=self._runtime.session.created_at,
        )

        self.open_context(
            context=context,
            provider_dir=session_path.provider_dir,
            owner_refs=[MemoryOwnerRef.user(user_id)],
            participant_refs=[
                MemoryParticipantRef.user(user_id),
                MemoryParticipantRef.avatar(self._avatar_id),
            ],
        )

        self._root_context_id = context.context_id

    async def on_session_start(self) -> None:
        if self._started:
            return

        if not self._processors_bound:
            raise RuntimeError("Memory processors have not been bound")

        await self._store.start()
        self._open_root_context()

        try:
            for processor in self._processors:
                await processor.start()
                self._started_processors.append(processor)

        except BaseException:
            for processor in reversed(self._started_processors):
                try:
                    await processor.stop(finalize=False)
                except Exception:
                    pass

            self._started_processors.clear()
            await self._store.stop()
            raise

        self._started = True

    async def on_session_stop(self) -> None:
        if not self._started and not self._started_processors:
            return

        errors: list[Exception] = []

        for processor in reversed(self._started_processors):
            try:
                await processor.stop()
            except Exception as exc:
                errors.append(exc)

        self._started_processors.clear()
        self._started = False

        try:
            await self._store.stop()
        except Exception as exc:
            errors.append(exc)

        if errors:
            raise ExceptionGroup(
                "Memory shutdown failed",
                errors,
            )
