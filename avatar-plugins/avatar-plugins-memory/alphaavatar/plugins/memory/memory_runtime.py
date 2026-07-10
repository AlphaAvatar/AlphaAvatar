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
import contextlib
import json
import os
from typing import Any

from livekit.agents.job import get_job_context
from livekit.agents.llm import ChatItem, ChatMessage

from alphaavatar.agents.avatar.prompting import MemoryPluginsTemplate
from alphaavatar.agents.constants import VIDEO_MEMORY_INTERVAL_SEC
from alphaavatar.agents.memory import (
    MemoryBase,
    MemoryCache,
    MemoryCacheType,
    MemoryItem,
    MemoryType,
    VectorRunnerOP,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation

from .graph import (
    GraphLookup,
    build_graph_from_mentions,
    save_graph_aliases,
    save_memory_graph_stubs,
)
from .log import logger
from .memory_delta_extractor import MemoryDeltaExtractor, MemoryProviderConfig
from .memory_markdown import save_memory_items_to_markdown
from .memory_op import MemoryDelta, PatchOp, flatten_items, norm_token, rebuild_from_items

ENV_MEMORY_UPDATE_INTERVAL_SEC = 30.0
ENV_MEMORY_ANNOTATION_GRACE_SEC = 0.75
ENV_MEMORY_CONSUMER_ID = "memory.env"


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

        # Only one ENV extraction is allowed at a time for this runtime.
        self._env_update_lock = asyncio.Lock()

        self._env_periodic_task: asyncio.Task[None] | None = None
        self._env_user_turn_task: asyncio.Task[None] | None = None

        # Additional memory-specific sampling on top of the shared perception
        # stream sampling.
        self._last_env_memory_frame_ts_by_source: dict[str, float] = {}

        self._executor = get_job_context().inference_executor

    @property
    def inference_method(self) -> str:
        method = os.getenv("MEMORY_INFERENCE_METHOD")

        if not method:
            raise RuntimeError(
                "MEMORY_INFERENCE_METHOD is not configured. "
                "Make sure AvatarPlugin.bootstrap_inference_runners() is called "
                "before MemoryRuntime is used."
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

    def _sample_env_observations_for_memory(
        self,
        observations: list[EnvObservation],
    ) -> list[EnvObservation]:
        """
        Apply Memory-specific video sampling.

        PerceptionRuntime owns transport buffering and consumer cursors.
        This method only decides which pending observations are meaningful
        enough to send to the ENV memory model.
        """

        if VIDEO_MEMORY_INTERVAL_SEC <= 0:
            return observations

        sampled: list[EnvObservation] = []

        for observation in observations:
            if observation.kind not in {
                "video_frame",
                "screen_frame",
            }:
                sampled.append(observation)
                continue

            try:
                timestamp = float(observation.timestamp)
            except (TypeError, ValueError):
                # Do not discard observations with non-numeric timestamps.
                sampled.append(observation)
                continue

            source_id = observation.source_id or observation.frame_id or "default"
            last_timestamp = self._last_env_memory_frame_ts_by_source.get(source_id)

            if (
                last_timestamp is not None
                and timestamp - last_timestamp < VIDEO_MEMORY_INTERVAL_SEC
            ):
                continue

            self._last_env_memory_frame_ts_by_source[source_id] = timestamp
            sampled.append(observation)

        return sampled

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
                object_ids=_merge_object_ids(
                    object_ids,
                    getattr(patch, "object_ids", []),
                ),
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

    def _build_env_evidence(self, observations: list[EnvObservation]) -> list[dict[str, Any]]:
        return [observation.to_evidence_dict() for observation in observations]

    def _build_env_conversation_context(
        self,
        *,
        messages: list[ChatItem],
    ) -> str | None:
        if not messages:
            return None

        context = MemoryPluginsTemplate.apply_search_template(
            messages,
            filter_roles=["system"],
        )

        return context or None

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

    async def _run_requested_env_update(self, *, trigger: str) -> None:
        try:
            await self._update_env_memory(
                session_id=self.session_runtime.session_id,
                trigger=trigger,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[Memory] requested env memory update failed. trigger=%s",
                trigger,
            )

    def _request_env_memory_update(self, *, trigger: str) -> None:
        if self._env_user_turn_task and not self._env_user_turn_task.done():
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "[Memory] env update request ignored because no running event loop is available."
            )
            return

        self._env_user_turn_task = loop.create_task(
            self._run_requested_env_update(
                trigger=trigger,
            ),
            name=(f"memory_env_user_turn_update:{self.session_runtime.session_id}"),
        )

    async def _update_env_memory(
        self,
        *,
        session_id: str | None = None,
        trigger: str = "manual",
        timeout: float = 25.0,
    ) -> list[MemoryItem]:
        sid = session_id or self.session_runtime.session_id

        if sid not in self.memory_cache:
            logger.warning("[Memory] env update skipped, cache not found: %s", sid)
            return []

        async with self._env_update_lock:
            cache = self.memory_cache[sid]
            window = self.perception_runtime.take_pending_observations(
                consumer_id=ENV_MEMORY_CONSUMER_ID,
                streams={"video", "screen"},
                require_payload=True,
                min_age_sec=ENV_MEMORY_ANNOTATION_GRACE_SEC,
            )
            raw_observations = window.observations

            if not raw_observations:
                # The window cursor may still have advanced over observations
                # without payload, so always commit the read result.
                self.perception_runtime.commit_observations(window)

                logger.debug(
                    "[Memory] env update skipped, no observations with payload. trigger=%s sid=%s",
                    trigger,
                    sid,
                )
                return []

            observations = self._sample_env_observations_for_memory(raw_observations)

            if not observations:
                # Commit all observations read for this consumer, including
                # frames skipped by Memory-specific sampling.
                self.perception_runtime.commit_observations(window)

                logger.debug(
                    "[Memory] env update skipped after sampling. "
                    "trigger=%s sid=%s raw_observations=%s",
                    trigger,
                    sid,
                    len(raw_observations),
                )
                return []

            messages = cache.take_pending_env_messages()

            evidence = self._build_env_evidence(observations)

            cache.evidence = evidence

            previous_env_memory = self.memory_state.render(
                memory_type=MemoryType.ENV,
                session_id=sid,
            )

            conversation_context = self._build_env_conversation_context(
                messages=messages,
            )

            delta = await self._delta_extractor.extract_env_delta(
                observations=observations,
                memory_cache=cache,
                previous_env_memory=previous_env_memory or None,
                conversation_context=conversation_context,
                timeout=timeout,
            )

            env_memories = self._build_memory_items_from_patches(
                memory_cache=cache,
                memory_type=MemoryType.ENV,
                patches=getattr(
                    delta,
                    "env_memory_entries",
                    [],
                ),
                object_ids=cache.object_ids,
                extra_data={
                    "trigger": trigger,
                    "evidence": evidence,
                },
            )

            # Extraction completed successfully, including the valid empty
            # delta case. Advance the memory consumer cursor and commit the
            # conversation messages associated with this observation window.
            self.perception_runtime.commit_observations(window)
            cache.commit_env_messages()

            if not env_memories:
                logger.debug(
                    "[Memory] env delta produced no memory. trigger=%s sid=%s observation_count=%s",
                    trigger,
                    sid,
                    len(observations),
                )
                return []

            self.env_memory = env_memories

            new_object_ids: list[str] = []

            for item in env_memories:
                new_object_ids.extend(item.object_ids)

            cache.add_object_ids(new_object_ids)

            logger.info(
                "[Memory] env memory updated. trigger=%s sid=%s generated=%s "
                "observations=%s raw_observations=%s",
                trigger,
                sid,
                len(env_memories),
                len(observations),
                len(raw_observations),
            )

            return env_memories

    async def _env_memory_loop(self, *, session_id: str) -> None:
        while True:
            await asyncio.sleep(ENV_MEMORY_UPDATE_INTERVAL_SEC)

            try:
                await self._update_env_memory(
                    session_id=session_id,
                    trigger="periodic",
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[Memory] periodic env memory update failed")

    async def _save_to_vdb(self, *, memory_items: list[dict], timeout: float) -> None:
        json_data = {
            "op": VectorRunnerOP.save,
            "param": {"memory_items": memory_items},
        }

        try:
            result = await asyncio.wait_for(
                self._executor.do_inference(
                    self.inference_method,
                    json.dumps(json_data).encode(),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error("Memory SAVE timeout!")
            return

        if result is None:
            logger.warning("Memory SAVE failed, result is None!")
            return

        payload = json.loads(result.decode())
        if payload.get("error") is not None:
            logger.error(f"Memory SAVE failed, because: {payload['error']}")
            return

        payload.pop("error", None)
        logger.info(f"Memory SAVE success: {payload}")

    """Base Op"""

    def on_cache_message_added(self, *, session_id: str, chat_item: ChatItem) -> None:
        if isinstance(chat_item, ChatMessage) and chat_item.role == "user":
            self._request_env_memory_update(trigger="user_turn")

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
            self._executor.do_inference(
                self.inference_method,
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
            self._executor.do_inference(
                self.inference_method,
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
                if has_tool_event:
                    conversation_delta, tool_delta = await asyncio.gather(
                        self._delta_extractor.extract_conversation_delta(
                            session_content=message_content,
                            memory_cache=cache,
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
                        timeout=30.0,
                    )
                    tool_delta = None

                conv_avatar, conv_user = self._apply_delta_to_bucket(
                    avatar_id=avatar_id,
                    delta=conversation_delta,
                    memory_cache=cache,
                    user_or_tool_memory_type=MemoryType.CONVERSATION,
                )

                all_assistant.extend(conv_avatar)
                all_user.extend(conv_user)

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

    async def save(
        self,
        timeout: float = 3,
    ) -> None:
        updated_items = [item for item in self.memory_items if item.updated]

        if not updated_items:
            logger.info("Memory SAVE skip!")
            return

        selected = sorted(
            updated_items,
            key=lambda item: item.timestamp or "",
        )

        memory_items: list[dict[str, Any]] = flatten_items(selected)

        if not memory_items:
            logger.info("Memory SAVE skip after flattening.")
            return

        avatar_path = self.session_runtime.avatar_path
        session_path = self.session_runtime.session_path

        if avatar_path is None:
            raise RuntimeError("SessionRuntime.avatar_path is not initialized")

        if session_path is None:
            raise RuntimeError("SessionRuntime.session_path is not initialized")

        try:
            markdown_result = save_memory_items_to_markdown(
                avatar_memory_path=avatar_path.memory_dir,
                session_memory_path=session_path.memory_dir,
                memory_items=memory_items,
            )

            logger.info("Memory local markdown backup success: %s", markdown_result)
        except Exception as e:
            logger.exception(f"Memory local markdown backup failed: {e}")

        try:
            graph_result = save_memory_graph_stubs(
                graph_path=avatar_path.graph_dir,
                memory_items=memory_items,
            )
            logger.info(f"Memory graph stubs save success: {graph_result}")
        except Exception as e:
            logger.exception(f"Memory graph stubs save failed: {e}")

        await self._save_to_vdb(memory_items=memory_items, timeout=timeout)

    """Runtime Op"""

    async def on_session_start(self) -> None:
        await super().on_session_start()

        sid = self.session_runtime.session_id

        if sid not in self.memory_cache:
            logger.debug("[Memory] env loop not started because memory cache is unavailable.")
            return

        if self._env_periodic_task is not None and not self._env_periodic_task.done():
            return

        self._env_periodic_task = asyncio.create_task(
            self._env_memory_loop(session_id=sid),
            name=(f"memory_env_periodic_loop:{sid}"),
        )

        logger.info(
            "[Memory] env memory loop started. sid=%s interval=%ss annotation_grace=%ss",
            sid,
            ENV_MEMORY_UPDATE_INTERVAL_SEC,
            ENV_MEMORY_ANNOTATION_GRACE_SEC,
        )

    async def on_session_stop(self) -> None:
        if self._env_periodic_task is not None:
            self._env_periodic_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await self._env_periodic_task

            self._env_periodic_task = None

        # Cancel an in-progress user-turn extraction. The final session-stop
        # extraction below will consume the still-uncommitted perception window.
        if self._env_user_turn_task is not None:
            if not self._env_user_turn_task.done():
                self._env_user_turn_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await self._env_user_turn_task

            self._env_user_turn_task = None

        try:
            await self._update_env_memory(
                session_id=self.session_runtime.session_id,
                trigger="session_stop",
                timeout=30.0,
            )
        except Exception:
            # Conversation/tool memory should still be updated and persisted
            # even if the final visual extraction fails.
            logger.exception("[Memory] final env memory update failed")

        # MemoryBase owns the final conversation/tool update and save.
        await super().on_session_stop()

        self._last_env_memory_frame_ts_by_source.clear()
