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

import asyncio
from collections.abc import Iterable
from typing import Any

from livekit.agents.llm import ChatItem, ChatMessage, FunctionCall, FunctionCallOutput

from alphaavatar.agents.memory import MemoryBase, MemoryContextState, MemoryPluginsTemplate
from alphaavatar.agents.memory.enums import MemoryCacheType, MemoryType
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

from .env_memory import EnvMemoryBatch, EnvMemoryScheduler
from .graph import GraphLookup, build_graph_from_mentions, save_graph_aliases
from .log import logger
from .memory_delta_extractor import MemoryDeltaExtractor, MemoryProviderConfig
from .memory_op import EnvMemoryDelta, MemoryDelta, PatchOp, norm_token, norm_topic
from .retrieval import MemoryRetrievalMixin
from .storage import MemoryStore
from .user_memory import MemoryConsolidator, MemoryPipelineConfig

CONVERSATION_PROCESSOR = "conversation"
TOOL_PROCESSOR = "tool"
ENV_PROCESSOR = "environment"


class MemoryRuntime(MemoryRetrievalMixin, MemoryBase):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        avatar_id: str,
        store: MemoryStore,
        memory_search_context: int = 3,
        memory_recall_num: int = 10,
        maximum_memory_num: int = 24,
        provider: dict[str, Any] | None = None,
        pipeline: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            runtime=runtime,
            avatar_id=avatar_id,
            memory_search_context=memory_search_context,
            memory_recall_num=memory_recall_num,
            maximum_memory_num=maximum_memory_num,
        )
        self._store = store
        self._provider_config = (
            MemoryProviderConfig(**provider) if provider else MemoryProviderConfig()
        )
        self._pipeline_config = (
            MemoryPipelineConfig(**pipeline) if pipeline else MemoryPipelineConfig()
        )
        self._delta_extractor = MemoryDeltaExtractor(self._provider_config)
        self._memory_consolidator = MemoryConsolidator(
            self._pipeline_config,
            candidate_search=self._consolidation_candidate_search,
            plan=self._delta_extractor.plan_consolidation,
        )
        self._env_scheduler: EnvMemoryScheduler | None = None
        self._processor_locks: dict[tuple[str, str], asyncio.Lock] = {}

    @property
    def store(self) -> MemoryStore:
        return self._store

    def _graph_lookup(self) -> GraphLookup:
        return GraphLookup(self.session_runtime.avatar_path.graph_dir)

    def _processor_lock(self, context_id: str, processor: str) -> asyncio.Lock:
        return self._processor_locks.setdefault((context_id, processor), asyncio.Lock())

    @staticmethod
    def _deduplicate_refs(refs: Iterable) -> list:
        return list({ref.key: ref for ref in refs}.values())

    @classmethod
    def _source_refs(cls, messages: list[ChatItem]) -> list[MemorySourceRef]:
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

        return cls._deduplicate_refs(refs)

    @classmethod
    def _tool_participants(
        cls,
        state: MemoryContextState,
        messages: list[ChatItem],
    ) -> list[MemoryParticipantRef]:
        refs = list(state.participant_refs)
        refs.extend(
            MemoryParticipantRef.tool(tool_id)
            for item in messages
            if isinstance(item, FunctionCall | FunctionCallOutput)
            and (tool_id := str(getattr(item, "name", "") or "").strip())
        )
        return cls._deduplicate_refs(refs)

    @staticmethod
    def _has_explicit_tool_event(messages: list[ChatItem]) -> bool:
        return any(
            isinstance(item, FunctionCall | FunctionCallOutput)
            or getattr(item, "tool_calls", None)
            or getattr(item, "function_call", None)
            or getattr(item, "type", None)
            in {"function_call", "function_call_output", "agent_config_update", "agent_handoff"}
            for item in messages
        )

    def _build_memory_items(
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

    def _apply_delta(
        self,
        *,
        state: MemoryContextState,
        delta: MemoryDelta,
        target_type: MemoryType,
        messages: list[ChatItem],
    ) -> tuple[list[MemoryItem], list[MemoryItem]]:
        source_refs = self._source_refs(messages)
        participants = (
            self._tool_participants(state, messages)
            if target_type is MemoryType.TOOLS
            else state.participant_refs
        )

        assistant = self._build_memory_items(
            state=state,
            memory_type=MemoryType.Avatar,
            patches=delta.assistant_memory_entries,
            owner_refs=[MemoryOwnerRef.avatar(self.avatar_id)],
            participant_refs=participants,
            source_refs=source_refs,
            scope=MemoryScope.owner(),
        )
        target = self._build_memory_items(
            state=state,
            memory_type=target_type,
            patches=delta.user_or_tool_memory_entries,
            owner_refs=state.owner_refs,
            participant_refs=participants,
            source_refs=source_refs,
            scope=MemoryScope.owner(),
        )
        return assistant, target

    def _build_context_content(
        self,
        state: MemoryContextState,
        messages: list[ChatItem],
    ) -> str:
        content = MemoryPluginsTemplate.apply_update_template(messages, state.cache_type)
        env_memory = self.memory_state.render(
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

    async def _checkpoint_window(
        self,
        state: MemoryContextState,
        processor: str,
    ) -> tuple[int, int, list[ChatItem]]:
        start = await self.store.get_checkpoint(
            context_id=state.context_id,
            processor=processor,
        )
        end = state.message_sequence

        if start > end:
            raise RuntimeError(
                f"Memory checkpoint exceeds context message sequence: "
                f"{state.context_id}:{processor} checkpoint={start} messages={end}"
            )

        return start, end, state.messages_between(start, end)

    def _apply_committed_items(self, items: list[MemoryItem]) -> None:
        superseded = {memory_id for item in items for memory_id in item.supersedes_memory_ids}

        if superseded:
            self.memory_state.discard(superseded)

        current = [item for item in items if item.memory_id not in superseded]

        for memory_type in MemoryType:
            bucket = [item for item in current if item.memory_type is memory_type]
            if bucket:
                self.memory_state.add(memory_type, bucket)

    async def _commit_items(
        self,
        *,
        state: MemoryContextState,
        processor: str,
        start: int,
        end: int,
        items: list[MemoryItem],
    ) -> None:
        await self.store.commit(
            items,
            context_id=state.context_id,
            processor=processor,
            idempotency_key=f"{state.context_id}:{processor}:{start}:{end}",
            checkpoint=MemoryCheckpointAdvance(
                from_sequence=start,
                to_sequence=end,
            ),
        )
        self._apply_committed_items(items)

    async def _update_conversation(self, state: MemoryContextState) -> None:
        async with self._processor_lock(state.context_id, CONVERSATION_PROCESSOR):
            start, end, messages = await self._checkpoint_window(
                state,
                CONVERSATION_PROCESSOR,
            )
            if start == end:
                return

            content = self._build_context_content(state, messages)
            delta = await self._delta_extractor.extract_conversation_delta(
                session_content=content,
                context_state=state,
                session_gate=self._pipeline_config.extraction.session_gate,
                timeout=30.0,
            )
            assistant, conversation = self._apply_delta(
                state=state,
                delta=delta,
                target_type=MemoryType.CONVERSATION,
                messages=messages,
            )
            conversation = await self._memory_consolidator.consolidate_session(
                conversation,
                session_content=content,
                updated_at=application_now(),
                trace_metadata=self._delta_extractor.base_trace_metadata(
                    context_state=state,
                    operation="memory_consolidation",
                    memory_type=MemoryType.CONVERSATION,
                    component="memory_consolidator",
                ),
            )
            await self._commit_items(
                state=state,
                processor=CONVERSATION_PROCESSOR,
                start=start,
                end=end,
                items=[*assistant, *conversation],
            )

    async def _update_tools(self, state: MemoryContextState) -> None:
        async with self._processor_lock(state.context_id, TOOL_PROCESSOR):
            start, end, messages = await self._checkpoint_window(
                state,
                TOOL_PROCESSOR,
            )
            if start == end:
                return

            if not self._has_explicit_tool_event(messages):
                await self._commit_items(
                    state=state,
                    processor=TOOL_PROCESSOR,
                    start=start,
                    end=end,
                    items=[],
                )
                return

            content = self._build_context_content(state, messages)
            delta = await self._delta_extractor.extract_tool_delta(
                session_content=content,
                context_state=state,
                timeout=30.0,
            )
            assistant, tools = self._apply_delta(
                state=state,
                delta=delta,
                target_type=MemoryType.TOOLS,
                messages=messages,
            )
            await self._commit_items(
                state=state,
                processor=TOOL_PROCESSOR,
                start=start,
                end=end,
                items=[*assistant, *tools],
            )

    async def _process_env_batch(
        self,
        batch: EnvMemoryBatch,
        timeout: float,
    ) -> list[MemoryItem]:
        state = self._get_context_state_or_raise(batch.context_id)
        previous = self.memory_state.render(
            memory_type=MemoryType.ENV,
            context_id=state.context_id,
        )

        delta: EnvMemoryDelta = await self._delta_extractor.extract_env_delta(
            memory_input=batch.memory_input,
            context_state=state,
            previous_env_memory=previous or None,
            conversation_context=batch.conversation_context,
            timeout=timeout,
        )
        items = self._build_memory_items(
            state=state,
            memory_type=MemoryType.ENV,
            patches=delta.env_memory_entries,
            owner_refs=state.owner_refs,
            participant_refs=state.participant_refs,
            source_refs=[
                MemorySourceRef.runtime_event(f"{state.context.session_id}:{event.sequence}")
                for event in batch.events
            ],
            scope=MemoryScope.context(state.context_id),
            extra_data={
                "trigger": batch.trigger_text,
                "perception_missed_count": batch.missed_count,
            },
        )
        await self._commit_items(
            state=state,
            processor=ENV_PROCESSOR,
            start=batch.from_sequence,
            end=batch.to_sequence,
            items=items,
        )
        return items

    def on_context_message_added(
        self,
        *,
        context_id: str,
        chat_item: ChatItem,
    ) -> None:
        if not isinstance(chat_item, ChatMessage) or chat_item.role != "user":
            return

        if self._env_scheduler is not None and context_id == self._env_scheduler.context_id:
            self._env_scheduler.request("user_turn")

    def save_graph_aliases(
        self,
        aliases: list[dict[str, Any]],
    ) -> dict[str, Any]:
        avatar_path = self.session_runtime.avatar_path
        if avatar_path is None:
            raise RuntimeError("SessionRuntime.avatar_path is not initialized")

        return save_graph_aliases(
            graph_path=avatar_path.graph_dir,
            aliases=aliases,
        )

    async def _update_context(self, state: MemoryContextState) -> None:
        if state.cache_type is MemoryCacheType.SESSION_INTERACTION:
            await asyncio.gather(
                self._update_conversation(state),
                self._update_tools(state),
            )
        elif state.cache_type is MemoryCacheType.AGENT_TOOL_INTERACTION:
            await self._update_tools(state)

    async def update(self, *, context_id: str | None = None) -> None:
        states = (
            [self._get_context_state_or_raise(context_id)]
            if context_id is not None
            else list(self.memory_contexts.values())
        )
        await asyncio.gather(*(self._update_context(state) for state in states))

    async def on_session_start(self) -> None:
        await self.store.start()

        try:
            await super().on_session_start()

            if self._root_context_id is None:
                return

            state = self._get_context_state_or_raise(self.root_context_id)
            initial_cutoff = self.perception_runtime.capture_cutoff()
            checkpoint = await self.store.get_checkpoint(
                context_id=state.context_id,
                processor=ENV_PROCESSOR,
            )

            if checkpoint > initial_cutoff.sequence:
                raise RuntimeError(
                    f"ENV checkpoint exceeds perception sequence: "
                    f"context={state.context_id} checkpoint={checkpoint} "
                    f"perception={initial_cutoff.sequence}"
                )

            if checkpoint < initial_cutoff.sequence:
                await self.store.commit(
                    [],
                    context_id=state.context_id,
                    processor=ENV_PROCESSOR,
                    idempotency_key=(
                        f"{state.context_id}:{ENV_PROCESSOR}:{checkpoint}:{initial_cutoff.sequence}"
                    ),
                    checkpoint=MemoryCheckpointAdvance(
                        from_sequence=checkpoint,
                        to_sequence=initial_cutoff.sequence,
                    ),
                )

            self._env_scheduler = EnvMemoryScheduler(
                perception_runtime=self.perception_runtime,
                context_state=state,
                initial_cutoff=initial_cutoff,
                process=self._process_env_batch,
                render_messages=lambda messages: MemoryPluginsTemplate.apply_update_template(
                    messages,
                    state.cache_type,
                ),
            )
            await self._env_scheduler.start()

        except BaseException:
            if self._env_scheduler is not None:
                try:
                    await self._env_scheduler.stop()
                except Exception:
                    logger.exception("Failed to rollback Memory ENV scheduler")
                self._env_scheduler = None

            await self.store.stop()
            raise

    async def on_session_stop(self) -> None:
        try:
            if self._env_scheduler is not None:
                await self._env_scheduler.stop()
                self._env_scheduler = None

            await super().on_session_stop()
        finally:
            await self.store.stop()
