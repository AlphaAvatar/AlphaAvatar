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

import asyncio
import pathlib
from abc import abstractmethod
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from livekit.agents.llm import ChatItem, ChatMessage, FunctionCall, FunctionCallOutput

from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.memory.enums import MemoryCacheType, MemoryType
from alphaavatar.agents.memory.schemas import (
    MemoryCheckpointAdvance,
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryParticipantRef,
    MemoryScope,
    MemorySourceRef,
)
from alphaavatar.agents.runtime import AvatarRuntime, SessionRuntime
from alphaavatar.agents.runtime.capability import AvatarCapability
from alphaavatar.agents.utils.time import application_now

from .processors.base import MemoryProcessor
from .schemas import PatchOp, norm_token, norm_topic
from .state import MemoryContextState, MemoryState
from .storage import MemoryStore
from .storage.graph import build_graph_from_mentions
from .template import MemoryPluginsTemplate

if TYPE_CHECKING:
    pass


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
        self._capabilities: tuple[AvatarCapability, ...] = ()

    @property
    def runtime(self) -> AvatarRuntime:
        return self._runtime

    @property
    def avatar_id(self) -> str:
        return self._avatar_id

    @property
    def store(self) -> MemoryStore:
        return self._store

    @property
    def capabilities(self) -> tuple[AvatarCapability, ...]:
        return self._capabilities

    @property
    def processors(self) -> tuple[MemoryProcessor, ...]:
        return self._processors

    @property
    def session_runtime(self) -> SessionRuntime:
        return self._runtime.session

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
    def memory_items(self) -> list[MemoryItem]:
        return self._memory_state.all_items

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

        self._processors = tuple(processors)
        self._processors_by_name = {processor.name: processor for processor in processors}
        self._processors_bound = True

        capabilities: dict[object, AvatarCapability] = {}
        for processor in processors:
            for capability in processor.capabilities:
                capabilities.setdefault(capability.name, capability)

        self._capabilities = tuple(capabilities.values())

    def processor(self, name: str) -> MemoryProcessor | None:
        return self._processors_by_name.get(name)

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
        for migration in self.session_runtime.pending_user_path_migrations:
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

    @staticmethod
    def deduplicate_refs(refs: Iterable) -> list:
        return list({ref.key: ref for ref in refs}.values())

    @classmethod
    def source_refs(cls, messages: list[ChatItem]) -> list[MemorySourceRef]:
        refs: list[MemorySourceRef] = []

        for item in messages:
            if isinstance(item, ChatMessage):
                if source_id := str(getattr(item, "id", "") or "").strip():
                    refs.append(MemorySourceRef.message(source_id))
                continue

            call_id = str(getattr(item, "call_id", "") or getattr(item, "id", "") or "").strip()
            tool_id = str(getattr(item, "name", "") or "").strip()

            if not call_id or not tool_id:
                continue

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

    def render_context_content(
        self,
        state: MemoryContextState,
        messages: list[ChatItem],
    ) -> str:
        content = MemoryPluginsTemplate.apply_update_template(
            messages,
            state.cache_type,
        )
        env_memory = self._memory_state.render(
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
        processor: str,
    ) -> tuple[int, int, list[ChatItem]]:
        start = await self._store.get_checkpoint(
            context_id=state.context_id,
            processor=processor,
        )
        end = state.message_sequence

        if start > end:
            raise RuntimeError(
                "Memory checkpoint exceeds context message sequence: "
                f"{state.context_id}:{processor} "
                f"checkpoint={start} messages={end}"
            )

        return start, end, state.messages_between(start, end)

    def apply_items(self, items: list[MemoryItem]) -> None:
        superseded = {memory_id for item in items for memory_id in item.supersedes_memory_ids}

        if superseded:
            self._memory_state.discard(superseded)

        current = [item for item in items if item.memory_id not in superseded]

        for memory_type in MemoryType:
            bucket = [item for item in current if item.memory_type is memory_type]
            if bucket:
                self._memory_state.add(memory_type, bucket)

    async def commit_items(
        self,
        *,
        state: MemoryContextState,
        processor: str,
        start: int,
        end: int,
        items: list[MemoryItem],
    ) -> None:
        await self._store.commit(
            items,
            context_id=state.context_id,
            processor=processor,
            idempotency_key=f"{state.context_id}:{processor}:{start}:{end}",
            checkpoint=MemoryCheckpointAdvance(
                from_sequence=start,
                to_sequence=end,
            ),
        )
        self.apply_items(items)

    def recall_owners(
        self,
        owner_refs: list[MemoryOwnerRef],
    ) -> list[MemoryOwnerRef]:
        return self.deduplicate_refs(
            [
                MemoryOwnerRef.avatar(self._avatar_id),
                *owner_refs,
            ]
        )

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

    @abstractmethod
    async def update(self, *, context_id: str | None = None) -> None:
        states = (
            [self.context_state(context_id)]
            if context_id is not None
            else list(self._memory_contexts.values())
        )

        await asyncio.gather(
            *(processor.update(state) for processor in self._processors for state in states)
        )

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

    # Temporary bridge for existing callers. Not part of MemoryBase.
    async def search_by_graph_node(self, **kwargs) -> list[MemoryItem]:
        processor = self._processors_by_name.get("retrieval")

        if processor is None:
            return []

        return await processor.search_graph(**kwargs)

    def _open_root_context(self) -> None:
        user_id = self.session_runtime.primary_user_id
        session_path = self.session_runtime.session_path

        if not user_id:
            return

        if session_path is None:
            raise RuntimeError("SessionRuntime.session_path is not initialized")

        context = MemoryContextRef(
            episode_id=uuid4().hex,
            context_id=uuid4().hex,
            session_id=self.session_runtime.session_id,
            created_at=self.session_runtime.created_at,
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
