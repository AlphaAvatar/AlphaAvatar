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
import os
from typing import Any

from livekit.agents.llm import ChatItem, ChatMessage

from alphaavatar.agents.memory import (
    MemoryBase,
    MemoryCache,
    MemoryCacheType,
    MemoryItem,
    MemoryPluginsTemplate,
    MemoryType,
)
from alphaavatar.agents.runtime import AvatarRuntime

from .env_memory import EnvMemoryBatch, EnvMemoryScheduler
from .graph import (
    GraphLookup,
    build_graph_from_mentions,
    save_graph_aliases,
)
from .log import logger
from .maintenance import RecallLedger
from .memory_delta_extractor import MemoryDeltaExtractor, MemoryProviderConfig
from .memory_op import (
    EnvMemoryDelta,
    MemoryDelta,
    PatchOp,
    norm_token,
    norm_topic,
)
from .persistence import MemoryPersistenceMixin
from .pipeline import MemoryPipelineConfig
from .retrieval import MemoryRetrievalMixin
from .user_memory import NoteConsolidator

ENV_SAVE_TIMEOUT_SEC = 8.0
SHUTDOWN_UPDATE_TIMEOUT_SEC = 12.0
SESSION_SAVE_TIMEOUT_SEC = 8.0


class MemoryRuntime(MemoryPersistenceMixin, MemoryRetrievalMixin, MemoryBase):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        avatar_id: str,
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

        self._provider_config = (
            MemoryProviderConfig(**provider) if provider else MemoryProviderConfig()
        )
        self._delta_extractor = MemoryDeltaExtractor(self._provider_config)

        self._pipeline_config = (
            MemoryPipelineConfig(**pipeline) if pipeline else MemoryPipelineConfig()
        )

        # User (conversation) memory: atomic item layer + note layer on top
        self._recall_ledger = RecallLedger()
        self._note_consolidator = NoteConsolidator(
            self._pipeline_config,
            candidate_search=self._note_candidate_search,
            consolidate=self._delta_extractor.consolidate_notes,
        )

        # ENV Memory init
        self._env_scheduler: EnvMemoryScheduler | None = None

        self._save_lock = asyncio.Lock()

    @property
    def vdb_inference_method(self) -> str:
        method = os.getenv("MEMORY_VDB_INFERENCE_METHOD")
        if not method:
            raise RuntimeError(
                "MEMORY_VDB_INFERENCE_METHOD is not configured. "
                "Make sure the Memory VDB runner is registered before "
                "MemoryRuntime starts."
            )
        return method

    """Helper Op"""

    def _graph_lookup(self) -> GraphLookup:
        return GraphLookup(self.session_runtime.avatar_path.graph_dir)

    def _apply_delta_to_bucket(
        self,
        *,
        avatar_id: str,
        delta: MemoryDelta,
        memory_cache: MemoryCache,
        user_or_tool_memory_type: MemoryType,
        target_object_ids: list[str] | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> tuple[list[MemoryItem], list[MemoryItem]]:
        assistant_memories = self._build_memory_items_from_patches(
            memory_cache=memory_cache,
            memory_type=MemoryType.Avatar,
            patches=delta.assistant_memory_entries,
            object_ids=[avatar_id],
            extra_data=extra_data,
        )

        target_memories = self._build_memory_items_from_patches(
            memory_cache=memory_cache,
            memory_type=user_or_tool_memory_type,
            patches=delta.user_or_tool_memory_entries,
            object_ids=target_object_ids or memory_cache.object_ids,
            extra_data=extra_data,
        )

        return assistant_memories, target_memories

    def _has_explicit_tool_event(self, chat_context: list[ChatItem]) -> bool:
        for item in chat_context:
            item_type = getattr(item, "type", None)

            if item_type in {
                "function_call",
                "function_call_output",
                "agent_config_update",
                "agent_handoff",
            }:
                return True

            if getattr(item, "tool_calls", None):
                return True

            if getattr(item, "function_call", None):
                return True

        return False

    def _build_memory_items_from_patches(
        self,
        *,
        memory_cache: MemoryCache,
        memory_type: MemoryType,
        patches: list[PatchOp],
        object_ids: list[str],
        extra_data: dict[str, Any] | None = None,
    ) -> list[MemoryItem]:
        items: list[MemoryItem] = []

        for patch in patches:
            topic = norm_topic(patch.topic)

            if not norm_token(patch.value):
                continue

            item = MemoryItem(
                updated=True,
                session_id=memory_cache.session_id,
                object_ids=object_ids,
                value=patch.value,
                topic=topic,
                timestamp=memory_cache.time,
                memory_type=memory_type,
                extra_data=dict(extra_data or {}),
            )

            graph_nodes, graph_links = build_graph_from_mentions(
                item=item,
                mentions=patch.node_mentions,
            )
            item.graph_nodes = graph_nodes
            item.graph_links = graph_links

            items.append(item)

        return items

    def _build_session_content_for_update(
        self,
        *,
        cache: MemoryCache,
    ) -> str:
        message_content = MemoryPluginsTemplate.apply_update_template(
            cache.messages,
            cache.cache_type,
        )

        current_session_env_memory = self.memory_state.render(
            memory_type=MemoryType.ENV,
            session_id=cache.session_id,
        )

        if not current_session_env_memory:
            return message_content

        return "\n\n".join(
            [
                message_content,
                "[CURRENT SESSION ENV MEMORY]",
                current_session_env_memory,
                "[END CURRENT SESSION ENV MEMORY]",
            ]
        )

    """Env Memory Op"""

    async def _process_env_batch(self, batch: EnvMemoryBatch, timeout: float) -> list[MemoryItem]:
        sid = batch.session_id

        if sid not in self.memory_cache:
            logger.warning(
                "[Memory] ENV processing skipped, cache not found: %s",
                sid,
            )
            return []

        cache = self.memory_cache[sid]
        evidence = batch.build_evidence()

        previous_env_memory = self.memory_state.render(
            memory_type=MemoryType.ENV,
            session_id=sid,
        )

        delta: EnvMemoryDelta = await self._delta_extractor.extract_env_delta(
            memory_input=batch.memory_input,
            memory_cache=cache,
            previous_env_memory=previous_env_memory or None,
            conversation_context=batch.conversation_context,
            timeout=timeout,
        )

        cache.evidence = evidence

        env_memories = self._build_memory_items_from_patches(
            memory_cache=cache,
            memory_type=MemoryType.ENV,
            patches=delta.env_memory_entries,
            object_ids=cache.object_ids,
            extra_data={
                "trigger": batch.trigger_text,
                # "evidence": evidence,  # TODO: Temporary annotation
                "perception_missed_count": batch.missed_count,
            },
        )

        if not env_memories:
            logger.debug(
                "[Memory] ENV delta produced no memory "
                "sid=%s trigger=%s observations=%s messages=%s",
                sid,
                batch.trigger_text,
                len(batch.observations),
                batch.message_count,
            )
            return []

        self.env_memory = env_memories

        cache.add_object_ids([object_id for item in env_memories for object_id in item.object_ids])

        saved = await self._persist_memory_items(
            env_memories,
            timeout=ENV_SAVE_TIMEOUT_SEC,
        )

        logger.info(
            "[Memory] ENV memory updated "
            "sid=%s trigger=%s generated=%s observations=%s "
            "raw_observations=%s messages=%s attempts=%s saved=%s",
            sid,
            batch.trigger_text,
            len(env_memories),
            len(batch.observations),
            batch.raw_observation_count,
            batch.message_count,
            batch.attempts + 1,
            saved,
        )

        return env_memories

    """Base Op"""

    def on_cache_message_added(
        self,
        *,
        session_id: str,
        chat_item: ChatItem,
    ) -> None:
        if not isinstance(chat_item, ChatMessage):
            return

        if chat_item.role != "user":
            return

        scheduler = self._env_scheduler

        if scheduler is None:
            return

        if session_id != scheduler.session_id:
            return

        scheduler.request("user_turn")

    def save_graph_aliases(self, aliases: list[dict[str, Any]]) -> dict[str, Any]:
        avatar_path = self.session_runtime.avatar_path

        if avatar_path is None:
            raise RuntimeError("SessionRuntime.avatar_path is not initialized")

        return save_graph_aliases(
            graph_path=avatar_path.graph_dir,
            aliases=aliases,
        )

    async def update(self, *, avatar_id: str, session_id: str | None = None):
        if session_id is not None and session_id not in self.memory_cache:
            raise ValueError(
                f"Session ID {session_id} not found in memory cache. "
                "You need to call 'init_cache' first."
            )

        memory_tuple = (
            [(sid, cache) for sid, cache in self.memory_cache.items()]
            if session_id is None
            else [(session_id, self.memory_cache[session_id])]
        )

        all_assistant: list[MemoryItem] = []
        all_user: list[MemoryItem] = []
        all_tool: list[MemoryItem] = []

        for current_sid, cache in memory_tuple:
            chat_context = cache.messages

            if not chat_context:
                logger.warning("[sid: %s] Memory message is empty, UPDATE skip!", current_sid)
                continue

            message_content = self._build_session_content_for_update(cache=cache)

            has_tool_event = self._has_explicit_tool_event(chat_context)

            if cache.cache_type == MemoryCacheType.SESSION_INTERACTION:
                if has_tool_event:
                    conversation_delta, tool_delta = await asyncio.gather(
                        self._delta_extractor.extract_conversation_delta(
                            session_content=message_content,
                            memory_cache=cache,
                            session_gate=self._pipeline_config.extraction.session_gate,
                            timeout=30.0,
                        ),
                        self._delta_extractor.extract_tool_delta(
                            session_content=message_content,
                            memory_cache=cache,
                            timeout=30.0,
                        ),
                    )
                else:
                    conversation_delta = await self._delta_extractor.extract_conversation_delta(
                        session_content=message_content,
                        memory_cache=cache,
                        session_gate=self._pipeline_config.extraction.session_gate,
                        timeout=30.0,
                    )
                    tool_delta = None

                conversation_avatar, conversation_items = self._apply_delta_to_bucket(
                    avatar_id=avatar_id,
                    delta=conversation_delta,
                    memory_cache=cache,
                    user_or_tool_memory_type=MemoryType.CONVERSATION,
                )

                all_assistant.extend(conversation_avatar)

                # Notes are built before the items are written, not after, so
                # each item lands once already carrying the back-reference of
                # the note that absorbed it. Re-saving them afterwards would
                # also re-append older sessions' items to THIS session's
                # markdown file.
                consolidated = await self._note_consolidator.consolidate_session(
                    conversation_items,
                    session_content=message_content,
                    memory_cache=cache,
                    recall_ledger=self._recall_ledger,
                    updated_at=self.context_runtime.timestamp.time_str,
                    trace_metadata=self._delta_extractor.base_trace_metadata(
                        memory_cache=cache,
                        operation="note_consolidation",
                        memory_type=MemoryType.CONVERSATION,
                        component="memory_note_consolidator",
                    ),
                )

                all_user.extend(consolidated.all_writes())

                if tool_delta is not None:
                    tool_avatar, tool_memories = self._apply_delta_to_bucket(
                        avatar_id=avatar_id,
                        delta=tool_delta,
                        memory_cache=cache,
                        user_or_tool_memory_type=MemoryType.TOOLS,
                    )

                    all_assistant.extend(tool_avatar)
                    all_tool.extend(tool_memories)

            else:
                if not has_tool_event:
                    logger.debug(
                        "[sid: %s] No explicit tool event found "
                        "for cache type %s, TOOL update skip.",
                        current_sid,
                        cache.cache_type,
                    )
                    continue

                tool_delta = await self._delta_extractor.extract_tool_delta(
                    session_content=message_content,
                    memory_cache=cache,
                    timeout=30.0,
                )

                tool_avatar, tool_memories = self._apply_delta_to_bucket(
                    avatar_id=avatar_id,
                    delta=tool_delta,
                    memory_cache=cache,
                    user_or_tool_memory_type=MemoryType.TOOLS,
                )

                all_assistant.extend(tool_avatar)
                all_tool.extend(tool_memories)

        self.avatar_memory = all_assistant
        self.user_memory = all_user
        self.tool_memory = all_tool

        # Persist the complete extracted lists, not self.memory_items.
        # MemoryState caps each bucket at maximum_memory_num -- a rendering
        # constraint ("the maximum number of memory items to use") -- so reading
        # the persistence path off it drops the earliest records of any type
        # that extracted more than the cap in one session. ENV already persists
        # its full batch directly for the same reason; this makes the
        # conversation, tool, and avatar paths behave the same way.
        extracted = all_assistant + all_user + all_tool

        if extracted and not await self._persist_memory_items(
            extracted,
            timeout=SESSION_SAVE_TIMEOUT_SEC,
        ):
            logger.warning("[Memory] session UPDATE persist incomplete; items remain pending.")

    async def save(self, timeout: float = 8.0) -> None:
        if not await self._persist_memory_items(
            self.memory_items,
            timeout=timeout,
        ):
            logger.warning("Memory SAVE incomplete; updated items remain pending.")

    """Runtime Op"""

    async def on_session_start(self) -> None:
        await super().on_session_start()

        sid = self.session_runtime.session_id
        cache = self.memory_cache.get(sid)

        if cache is None:
            logger.debug("[Memory] ENV scheduler not started because memory cache is unavailable.")
            return

        self._env_scheduler = EnvMemoryScheduler(
            perception_runtime=self.perception_runtime,
            memory_cache=cache,
            process=self._process_env_batch,
            render_messages=lambda messages: MemoryPluginsTemplate.apply_update_template(
                messages,
                cache.cache_type,
            ),
        )

        await self._env_scheduler.start()

        logger.info("[Memory] ENV scheduler started sid=%s", sid)

    async def on_session_stop(self) -> None:
        if self._env_scheduler is not None:
            await self._env_scheduler.stop()
            self._env_scheduler = None

        await super().on_session_stop()
