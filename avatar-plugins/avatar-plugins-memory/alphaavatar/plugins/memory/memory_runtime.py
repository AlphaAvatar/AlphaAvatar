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
import json
import os
from typing import Any

from livekit.agents.llm import ChatItem, ChatMessage

from alphaavatar.agents.memory import (
    MemoryBase,
    MemoryCache,
    MemoryCacheType,
    MemoryItem,
    MemoryNote,
    MemoryPluginsTemplate,
    MemoryType,
    VectorRunnerOP,
)
from alphaavatar.agents.runtime import AvatarRuntime

from .env_memory import EnvMemoryBatch, EnvMemoryScheduler
from .graph import (
    GraphLookup,
    build_graph_from_mentions,
    save_graph_aliases,
    save_memory_graph_stubs,
)
from .log import logger
from .maintenance import JudgeDecision, JudgeVerdict
from .memory_delta_extractor import MemoryDeltaExtractor, MemoryProviderConfig
from .memory_markdown import save_memory_items_to_markdown
from .memory_op import (
    EnvMemoryDelta,
    MemoryDelta,
    PatchOp,
    flatten_records,
    norm_token,
    rebuild_from_items,
)
from .pipeline import MemoryPipelineConfig, build_maintenance_strategy

ENV_SAVE_TIMEOUT_SEC = 8.0
SHUTDOWN_UPDATE_TIMEOUT_SEC = 12.0
SESSION_SAVE_TIMEOUT_SEC = 8.0


def _norm_topic(value: str | None) -> str | None:
    if not value:
        return None

    value = " ".join(value.strip().split())
    return value.lower()[:64]


def _merge_object_ids(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value is None:
            continue

        items = value if isinstance(value, list) else [value]

        for item in items:
            normalized = str(item).strip()

            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            merged.append(normalized)

    return merged


def _render_judge_payload(
    *,
    incoming: list[MemoryItem],
    candidates_by_index: dict[int, list[MemoryItem]],
    allow_update: bool,
) -> str:
    allowed = "add, noop, update" if allow_update else "add, noop"
    blocks = [f"Allowed decisions: {allowed}", ""]

    for index, record in enumerate(incoming):
        blocks.append(f"### Incoming memory [index={index}]")
        blocks.append(record.render_line())
        blocks.append("")
        blocks.append("Existing memories close to it:")

        candidates = candidates_by_index.get(index) or []
        if not candidates:
            blocks.append("(none)")
        else:
            for candidate in candidates:
                blocks.append(f"- id={candidate.memory_id}: {candidate.render_line()}")
        blocks.append("")

    return "\n".join(blocks)


def _collect_update_targets(
    *,
    verdicts: list[JudgeVerdict],
    candidates_by_index: dict[int, list[MemoryItem]],
) -> list[MemoryItem]:
    targets: dict[str, MemoryItem] = {}

    for verdict in verdicts:
        if verdict.decision != JudgeDecision.UPDATE:
            continue

        by_id = {c.memory_id: c for c in candidates_by_index.get(verdict.index) or []}
        for target_id in verdict.target_ids:
            candidate = by_id.get(target_id)
            if candidate is not None:
                targets[target_id] = candidate

    return list(targets.values())


def _render_rewrite_payload(
    *,
    incoming: list[MemoryItem],
    targets: list[MemoryItem],
) -> str:
    blocks = ["### Incoming memories", ""]
    blocks.extend(record.render_line() for record in incoming)
    blocks.append("")
    blocks.append("### Existing memories to rewrite (return one object each, same order)")
    blocks.append("")
    blocks.extend(f"- id={t.memory_id}: {t.render_line()}" for t in targets)
    return "\n".join(blocks)


class MemoryRuntime(MemoryBase):
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

        self._maintenance = build_maintenance_strategy(
            self._pipeline_config.maintenance,
            candidate_search=self._maintenance_candidate_search,
            judge=self._maintenance_judge,
            rewriter=self._maintenance_rewrite,
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
            topic = _norm_topic(patch.topic)

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

    async def _save_to_vdb(self, *, memory_items: list[dict], timeout: float) -> bool:
        json_data = {
            "op": VectorRunnerOP.save,
            "param": {"memory_items": memory_items},
        }

        try:
            result = await asyncio.wait_for(
                self.inference_executor.do_inference(
                    self.vdb_inference_method,
                    json.dumps(json_data).encode(),
                ),
                timeout=timeout,
            )
        except TimeoutError:
            logger.error("Memory SAVE timeout!")
            return False
        except Exception:
            logger.exception("Memory SAVE failed")
            return False

        if result is None:
            logger.warning("Memory SAVE failed, result is None!")
            return False

        try:
            payload = json.loads(result.decode())
        except Exception:
            logger.exception("Memory SAVE returned invalid JSON")
            return False

        if payload.get("error") is not None:
            logger.error(
                "Memory SAVE failed, because: %s",
                payload["error"],
            )
            return False

        logger.info(
            "Memory SAVE success: %s",
            {key: value for key, value in payload.items() if key != "error"},
        )
        return True

    async def _persist_memory_items(
        self,
        items: list[MemoryItem],
        *,
        timeout: float,
    ) -> bool:
        async with self._save_lock:
            selected = sorted(
                (item for item in items if item.updated),
                key=lambda item: item.timestamp or "",
            )

            if not selected:
                return True

            flattened = flatten_records(selected, include_topic=True)

            if not flattened:
                return True

            avatar_path = self.session_runtime.avatar_path
            session_path = self.session_runtime.session_path

            if avatar_path is None:
                raise RuntimeError("SessionRuntime.avatar_path is not initialized")

            if session_path is None:
                raise RuntimeError("SessionRuntime.session_path is not initialized")

            markdown_result, graph_result = await asyncio.gather(
                asyncio.to_thread(
                    save_memory_items_to_markdown,
                    avatar_memory_path=avatar_path.memory_dir,
                    session_memory_path=session_path.memory_dir,
                    memory_items=flattened,
                ),
                asyncio.to_thread(
                    save_memory_graph_stubs,
                    graph_path=avatar_path.graph_dir,
                    memory_items=flattened,
                ),
                return_exceptions=True,
            )

            if isinstance(markdown_result, Exception):
                logger.error(
                    "Memory local markdown backup failed",
                    exc_info=(
                        type(markdown_result),
                        markdown_result,
                        markdown_result.__traceback__,
                    ),
                )
            else:
                logger.info(
                    "Memory local markdown backup success: %s",
                    markdown_result,
                )

            if isinstance(graph_result, Exception):
                logger.error(
                    "Memory graph stubs save failed",
                    exc_info=(
                        type(graph_result),
                        graph_result,
                        graph_result.__traceback__,
                    ),
                )
            else:
                logger.info(
                    "Memory graph stubs save success: %s",
                    graph_result,
                )

            if not await self._save_to_vdb(
                memory_items=flattened,
                timeout=timeout,
            ):
                return False

            self.memory_state.mark_saved({item.memory_id for item in selected})
            return True

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

    async def search_by_context(
        self,
        *,
        avatar_id: str,
        session_id: str,
        chat_context: list[ChatItem],
        timeout: float = 3,
    ) -> None:
        """Search for relevant memories based on the query."""
        context_str = MemoryPluginsTemplate.apply_search_template(
            chat_context[-getattr(self, "memory_search_context", 3) :],
            filter_roles=["system"],
        )

        if not context_str:
            return

        json_data = {
            "op": VectorRunnerOP.search_by_context,
            "param": {
                "context_str": context_str,
                "object_ids": _merge_object_ids(
                    [avatar_id],
                    self.memory_cache[session_id].object_ids,
                ),
                "top_k": self.memory_recall_num,
            },
        }

        result = await asyncio.wait_for(
            self.inference_executor.do_inference(
                self.vdb_inference_method,
                json.dumps(json_data).encode(),
            ),
            timeout=timeout,
        )

        if result is None:
            logger.warning("Memory [search_by_context] failed, result is None!")
            return

        data: dict[str, Any] = json.loads(result.decode())

        if data.get("memory_items"):
            memory_items = rebuild_from_items(data["memory_items"])

            self.avatar_memory = [
                item for item in memory_items if item.memory_type == MemoryType.Avatar
            ]

            self.user_memory = [
                item for item in memory_items if item.memory_type == MemoryType.CONVERSATION
            ]

            self.tool_memory = [
                item for item in memory_items if item.memory_type == MemoryType.TOOLS
            ]

            self.env_memory = [item for item in memory_items if item.memory_type == MemoryType.ENV]

        if data.get("error"):
            logger.warning("Memory [search_by_context] err: %s", data["error"])

    async def search_by_graph_node(
        self,
        *,
        node_key: str | None = None,
        node_query: str | None = None,
        object_ids: list[str] | None = None,
        session_id: str | None = None,
        memory_type: str | None = None,
        node_type: str | None = None,
        max_hops: int = 0,
        top_k: int = 50,
        timeout: float = 3,
    ) -> list[MemoryItem]:
        node_keys: list[str] = []

        if node_key:
            lookup = self._graph_lookup()
            resolved = lookup.resolve_keys(node_key)

            if max_hops > 0:
                node_keys = lookup.expand_node_keys(
                    node_keys=resolved,
                    max_hops=max_hops,
                    max_neighbors_per_node=16,
                    min_weight=0.0,
                )
            else:
                node_keys = resolved

        json_data = {
            "op": VectorRunnerOP.search_by_graph_node,
            "param": {
                "node_keys": node_keys,
                "node_query": node_query,
                "object_ids": object_ids,
                "session_id": session_id,
                "memory_type": memory_type,
                "node_type": node_type,
                "top_k": top_k,
            },
        }

        result = await asyncio.wait_for(
            self.inference_executor.do_inference(
                self.vdb_inference_method,
                json.dumps(json_data).encode(),
            ),
            timeout=timeout,
        )

        if result is None:
            logger.warning("Memory [search_by_graph_node] failed, result is None!")
            return []

        data: dict[str, Any] = json.loads(result.decode())

        if data.get("error"):
            logger.warning("Memory [search_by_graph_node] err: %s", data["error"])
            return []

        return rebuild_from_items(data.get("memory_items") or [])

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
                extraction = self._pipeline_config.extraction

                if has_tool_event:
                    conversation_delta, tool_delta = await asyncio.gather(
                        self._delta_extractor.extract_conversation_note(
                            session_content=message_content,
                            memory_cache=cache,
                            session_gate=extraction.session_gate,
                            keywords=extraction.keywords,
                            timeout=30.0,
                        ),
                        self._delta_extractor.extract_tool_delta(
                            session_content=message_content,
                            memory_cache=cache,
                            timeout=30.0,
                        ),
                    )
                else:
                    conversation_delta = await self._delta_extractor.extract_conversation_note(
                        session_content=message_content,
                        memory_cache=cache,
                        session_gate=extraction.session_gate,
                        keywords=extraction.keywords,
                        timeout=30.0,
                    )
                    tool_delta = None

                all_assistant.extend(
                    self._build_memory_items_from_patches(
                        memory_cache=cache,
                        memory_type=MemoryType.Avatar,
                        patches=conversation_delta.assistant_memory_entries,
                        object_ids=[avatar_id],
                    )
                )

                note_patch = conversation_delta.note
                if norm_token(note_patch.summary) or note_patch.facts:
                    note = MemoryNote(
                        updated=True,
                        session_id=cache.session_id,
                        object_ids=cache.object_ids,
                        topic=_norm_topic(note_patch.topic),
                        timestamp=cache.time,
                        memory_type=MemoryType.CONVERSATION,
                        summary=note_patch.summary,
                        facts=list(note_patch.facts),
                        keywords=list(note_patch.keywords),
                    )

                    maintained = await self._maintenance.apply(
                        [note],
                        trace_metadata=self._delta_extractor.base_trace_metadata(
                            memory_cache=cache,
                            operation="maintenance",
                            memory_type=MemoryType.CONVERSATION,
                            component="memory_maintenance",
                        ),
                    )

                    logger.info(
                        "[sid: %s] maintenance inserted=%d rewritten=%d dropped=%d",
                        current_sid,
                        len(maintained.to_insert),
                        len(maintained.to_rewrite),
                        len(maintained.dropped),
                    )

                    all_user.extend(maintained.all_writes())

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

    """Maintenance Op"""

    async def _maintenance_candidate_search(
        self,
        texts: list[str],
        *,
        timeout: float = 5.0,
    ) -> list[list[dict[str, Any]]]:
        empty: list[list[dict[str, Any]]] = [[] for _ in texts]

        if not texts:
            return []

        json_data = {
            "op": VectorRunnerOP.search_similar_batch,
            "param": {
                "texts": texts,
                "top_k": self._pipeline_config.maintenance.max_candidates_per_note,
                "object_ids": _merge_object_ids([self.avatar_id]),
                "memory_type": MemoryType.CONVERSATION.value,
            },
        }

        try:
            result = await asyncio.wait_for(
                self.inference_executor.do_inference(
                    self.vdb_inference_method,
                    json.dumps(json_data).encode(),
                ),
                timeout=timeout,
            )
        except Exception as e:
            logger.warning("Memory [maintenance candidate search] failed: %s", e)
            return empty

        if result is None:
            return empty

        data = json.loads(result.decode())

        if data.get("error"):
            logger.warning("Memory [maintenance candidate search] err: %s", data["error"])
            return empty

        results = data.get("results") or []

        # Never let a short response shift candidates onto the wrong record.
        if len(results) != len(texts):
            logger.warning(
                "Memory [maintenance] candidate count mismatch: got %d want %d",
                len(results),
                len(texts),
            )
            return empty

        return results

    async def _maintenance_judge(
        self,
        *,
        incoming: list[MemoryItem],
        candidates_by_index: dict[int, list[MemoryItem]],
        allow_update: bool,
        trace_metadata: dict[str, Any],
    ) -> list[JudgeVerdict]:
        payload = _render_judge_payload(
            incoming=incoming,
            candidates_by_index=candidates_by_index,
            allow_update=allow_update,
        )

        verdicts = await self._delta_extractor.judge_maintenance(
            payload=payload,
            metadata={**trace_metadata, "operation": "maintenance_judge"},
            timeout=self._pipeline_config.maintenance.timeout,
        )
        return verdicts.verdicts

    async def _maintenance_rewrite(
        self,
        *,
        incoming: list[MemoryItem],
        verdicts: list[JudgeVerdict],
        candidates_by_index: dict[int, list[MemoryItem]],
        trace_metadata: dict[str, Any],
    ) -> dict[str, MemoryItem]:
        targets = _collect_update_targets(
            verdicts=verdicts,
            candidates_by_index=candidates_by_index,
        )

        if not targets:
            return {}

        payload = _render_rewrite_payload(incoming=incoming, targets=targets)

        rewritten = await self._delta_extractor.rewrite_memories(
            payload=payload,
            metadata={**trace_metadata, "operation": "maintenance_rewrite"},
            timeout=self._pipeline_config.maintenance.timeout,
        )

        by_id: dict[str, MemoryItem] = {}
        target_by_id = {t.memory_id: t for t in targets}

        for update in rewritten.updates:
            original = target_by_id.get(update.id)
            if not isinstance(original, MemoryNote):
                continue

            # Immutable update: a new object. The original memory_id is kept so
            # the VDB save (delete-by-id + reinsert) acts as an upsert, and the
            # original timestamp is kept because it records when the fact was
            # observed -- overwriting it would corrupt temporal reasoning.
            # `value` is recomposed by the MemoryNote validator.
            by_id[update.id] = MemoryNote(
                # _persist_memory_items only writes records flagged as updated;
                # a rewritten note must carry the flag or it never reaches the VDB.
                updated=True,
                memory_id=original.memory_id,
                session_id=original.session_id,
                object_ids=list(original.object_ids),
                topic=original.topic,
                timestamp=original.timestamp,
                memory_type=original.memory_type,
                summary=update.summary or original.summary,
                facts=list(update.facts or original.facts),
                keywords=list(update.keywords or original.keywords),
                graph_nodes=list(original.graph_nodes),
                graph_links=list(original.graph_links),
                extra_data={
                    **original.extra_data,
                    "updated_at": self.context_runtime.timestamp.time_str,
                    "updated_in_session": self.session_runtime.session_id,
                },
            )

        return by_id

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
