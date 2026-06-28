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
import asyncio
import json
import os
from typing import Any

from livekit.agents.job import get_job_context
from livekit.agents.llm import ChatItem
from pydantic import BaseModel, Field

from alphaavatar.agents.avatar.prompting import MemoryPluginsTemplate
from alphaavatar.agents.memory import (
    MemoryBase,
    MemoryCache,
    MemoryItem,
    MemoryType,
    VectorRunnerOP,
)
from alphaavatar.agents.providers import (
    ProviderGateway,
    ProvidersConfig,
)
from alphaavatar.agents.runtime import SessionRuntime

from .graph import (
    GraphLookup,
    build_graph_from_mentions,
    save_graph_aliases,
    save_memory_graph_stubs,
)
from .log import logger
from .memory_markdown import save_memory_items_to_markdown
from .memory_op import MemoryDelta, PatchOp, flatten_items, norm_token, rebuild_from_items
from .memory_prompts import (
    CONVERSATION_DELTA_PROMPT,
    TOOL_DELTA_PROMPT,
)


def _norm_topic(t: str | None) -> str | None:
    if not t:
        return None
    t = " ".join(t.strip().split())
    return t.lower()[:64]


def _merge_object_ids(*values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value is None:
            continue

        items = value if isinstance(value, list) else [value]

        for item in items:
            s = str(item).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)

    return out


class MemoryProviderConfig(BaseModel):
    conversation_delta_task: str = "memory.conversation_delta"
    tool_delta_task: str = "memory.tool_delta"
    gateway: ProvidersConfig = Field(default_factory=ProvidersConfig)


class MemoryRuntime(MemoryBase):
    def __init__(
        self,
        *,
        session_runtime: SessionRuntime,
        memory_search_context: int = 3,
        memory_recall_num: int = 10,
        maximum_memory_num: int = 24,
        provider: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            session_runtime=session_runtime,
            memory_search_context=memory_search_context,
            memory_recall_num=memory_recall_num,
            maximum_memory_num=maximum_memory_num,
        )

        self._provider_config = (
            MemoryProviderConfig(**provider) if provider else MemoryProviderConfig()
        )

        self._conversation_delta_task = self._provider_config.conversation_delta_task
        self._tool_delta_task = self._provider_config.tool_delta_task

        self._provider_gateway = ProviderGateway(self._provider_config.gateway)
        self._provider_gateway.validate_tasks(
            [
                self._conversation_delta_task,
                self._tool_delta_task,
            ]
        )

        self._executor = get_job_context().inference_executor

    @property
    def inference_method(self) -> str:
        method = os.getenv("MEMORY_INFERENCE_METHOD")
        if not method:
            raise RuntimeError(
                "MEMORY_INFERENCE_METHOD is not configured. "
                "Make sure AvatarPlugin.bootstrap_inference_runners() is called before "
                "MemoryLangChain is used."
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
    ) -> tuple[list[MemoryItem], list[MemoryItem]]:
        updated_time = memory_cache.time
        assistant_memories: list[MemoryItem] = []
        target_memories: list[MemoryItem] = []

        def _maybe_add(
            *,
            bucket: list[MemoryItem],
            object_ids: list[str],
            mem_type: MemoryType,
            patch: PatchOp,
        ) -> None:
            topic = _norm_topic(patch.topic)

            if not norm_token(patch.value):
                return

            extra_data: dict[str, Any] = {}
            runtime_evidence = getattr(memory_cache, "evidence", None)
            if runtime_evidence:
                extra_data["evidence"] = runtime_evidence

            memory_item = MemoryItem(
                updated=True,
                session_id=memory_cache.session_id,
                object_ids=object_ids,
                value=patch.value,
                topic=topic,
                timestamp=updated_time,
                memory_type=mem_type,
                extra_data=extra_data,
            )

            graph_nodes, graph_links = build_graph_from_mentions(
                item=memory_item,
                mentions=patch.node_mentions,
            )
            memory_item.graph_nodes = graph_nodes
            memory_item.graph_links = graph_links

            bucket.append(memory_item)

        for patch in delta.assistant_memory_entries:
            _maybe_add(
                bucket=assistant_memories,
                object_ids=[avatar_id],
                mem_type=MemoryType.Avatar,
                patch=patch,
            )

        for patch in delta.user_or_tool_memory_entries:
            _maybe_add(
                bucket=target_memories,
                object_ids=memory_cache.object_ids,
                mem_type=user_or_tool_memory_type,
                patch=patch,
            )

        return assistant_memories, target_memories

    def _has_explicit_tool_event(self, chat_context: list[ChatItem]) -> bool:
        for item in chat_context:
            item_type = getattr(item, "type", None)

            if item_type in {
                "function_call",
                "function_call_output",
                "agent_config_update",
            }:
                return True

            if item_type == "agent_handoff":
                return True

            if getattr(item, "tool_calls", None):
                return True

            if getattr(item, "function_call", None):
                return True

        return False

    async def _safe_ainvoke_delta(
        self,
        *,
        task_name: str,
        prompt,
        payload: dict[str, Any],
        metadata: dict[str, Any],
        timeout: float = 12.0,
    ) -> MemoryDelta:
        try:
            result = await asyncio.wait_for(
                self._provider_gateway.ainvoke_structured(
                    task_name=task_name,
                    prompt=prompt,
                    payload=payload,
                    output_schema=MemoryDelta,
                    metadata=metadata,
                ),
                timeout=timeout,
            )

            if isinstance(result.output, MemoryDelta):
                return result.output

            return MemoryDelta.model_validate(result.output)

        except asyncio.TimeoutError:
            logger.warning("[Memory] delta extraction timeout task=%s", task_name)
            return MemoryDelta()
        except Exception:
            logger.exception("[Memory] delta extraction failed task=%s", task_name)
            return MemoryDelta()

    async def _safe_ainvoke_conversation_delta(
        self,
        *,
        session_content: str,
        memory_cache: MemoryCache,
        timeout: float = 12.0,
    ) -> MemoryDelta:
        payload = {
            "type": MemoryType.CONVERSATION,
            "session_content": session_content,
        }

        return await self._safe_ainvoke_delta(
            task_name=self._conversation_delta_task,
            prompt=CONVERSATION_DELTA_PROMPT,
            payload=payload,
            metadata={
                "provider_dir": memory_cache.provider_dir,
                "plugin": "memory",
                "component": "memory_delta_extractor",
                "operation": "conversation_delta",
                "session_id": memory_cache.session_id,
                "object_ids": memory_cache.object_ids,
                "memory_type": str(memory_cache.type),
            },
            timeout=timeout,
        )

    async def _safe_ainvoke_tool_delta(
        self,
        *,
        session_content: str,
        memory_cache: MemoryCache,
        timeout: float = 12.0,
    ) -> MemoryDelta:
        payload = {
            "type": MemoryType.TOOLS,
            "session_content": session_content,
        }

        return await self._safe_ainvoke_delta(
            task_name=self._tool_delta_task,
            prompt=TOOL_DELTA_PROMPT,
            payload=payload,
            metadata={
                "provider_dir": memory_cache.provider_dir,
                "plugin": "memory",
                "component": "memory_delta_extractor",
                "operation": "tool_delta",
                "session_id": memory_cache.session_id,
                "object_ids": memory_cache.object_ids,
                "memory_type": str(memory_cache.type),
            },
            timeout=timeout,
        )

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

    async def search_by_context(
        self, *, avatar_id: str, session_id: str, chat_context: list[ChatItem], timeout: float = 3
    ) -> None:
        """Search for relevant memories based on the query."""
        context_str = MemoryPluginsTemplate.apply_search_template(
            chat_context[-getattr(self, "memory_search_context", 3) :], filter_roles=["system"]
        )

        if not context_str:
            return

        json_data = {
            "op": VectorRunnerOP.search_by_context,
            "param": {
                "context_str": context_str,
                "object_ids": _merge_object_ids(
                    [avatar_id], self.memory_cache[session_id].object_ids
                ),
                "top_k": self.memory_recall_num,
            },
        }
        json_data = json.dumps(json_data).encode()

        result = await asyncio.wait_for(
            self._executor.do_inference(self.inference_method, json_data),
            timeout=timeout,
        )

        if result is None:
            logger.warning("Memory [search_by_context] falied, result is None!")
            return

        data: dict[str, Any] = json.loads(result.decode())

        # Update Current Memory
        if data.get("memory_items", None):
            memory_items = rebuild_from_items(data["memory_items"])

            self.avatar_memory = [it for it in memory_items if it.memory_type == MemoryType.Avatar]
            self.user_memory = [
                it for it in memory_items if it.memory_type == MemoryType.CONVERSATION
            ]
            self.tool_memory = [it for it in memory_items if it.memory_type == MemoryType.TOOLS]
            self.env_memory = [it for it in memory_items if it.memory_type == MemoryType.ENV]

        if data.get("error", None):
            logger.warning(f"Memory [search_by_context] err: {data['error']}")

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
            logger.warning(f"Memory [search_by_graph_node] err: {data['error']}")
            return []

        return rebuild_from_items(data.get("memory_items") or [])

    async def update(self, *, avatar_id: str, session_id: str | None = None):
        if session_id is not None and session_id not in self.memory_cache:
            raise ValueError(
                f"Session ID {session_id} not found in memory cache. You need to call 'init_cache' first."
            )

        memory_tuple = (
            [(sid, cache) for sid, cache in self.memory_cache.items()]
            if session_id is None
            else [(session_id, self.memory_cache[session_id])]
        )

        all_assistant: list[MemoryItem] = []
        all_user: list[MemoryItem] = []
        all_tool: list[MemoryItem] = []

        for _sid, cache in memory_tuple:
            chat_context = cache.messages
            if not chat_context:
                logger.warning(f"[sid: {_sid}] Memory message is empty, UPDATE skip!")
                continue

            message_content: str = MemoryPluginsTemplate.apply_update_template(
                chat_context, cache.type
            )

            has_tool_event = self._has_explicit_tool_event(chat_context)

            if cache.type == MemoryType.CONVERSATION:
                if has_tool_event:
                    conversation_delta, tool_delta = await asyncio.gather(
                        self._safe_ainvoke_conversation_delta(
                            session_content=message_content,
                            memory_cache=cache,
                            timeout=30.0,
                        ),
                        self._safe_ainvoke_tool_delta(
                            session_content=message_content,
                            memory_cache=cache,
                            timeout=30.0,
                        ),
                    )
                else:
                    conversation_delta = await self._safe_ainvoke_conversation_delta(
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
                        f"[sid: {_sid}] No explicit tool event found for cache type {cache.type}, TOOL update skip."
                    )
                    continue

                tool_delta = await self._safe_ainvoke_tool_delta(
                    message_content=message_content,
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

    async def save(self, timeout: float = 3):
        updated_items: list[MemoryItem] = [item for item in self.memory_items if item.updated]

        if not updated_items:
            logger.info("Memory SAVE skip!")
            return

        selected = sorted(updated_items, key=lambda x: x.timestamp or "")
        memory_items: list[dict] = flatten_items(selected)

        if not memory_items:
            logger.info("Memory SAVE skip after flattening.")
            return

        try:
            md_result = save_memory_items_to_markdown(
                avatar_memory_path=self.session_runtime.avatar_path.memory_dir,
                session_memory_path=self.session_runtime.session_path.memory_dir,
                memory_items=memory_items,
            )
            logger.info(f"Memory local markdown backup success: {md_result}")
        except Exception as e:
            logger.error(f"Memory local markdown backup failed: {e}")

        try:
            graph_result = save_memory_graph_stubs(
                graph_path=self.session_runtime.avatar_path.graph_dir,
                memory_items=memory_items,
            )
            logger.info(f"Memory graph stubs save success: {graph_result}")
        except Exception as e:
            logger.error(f"Memory graph stubs save failed: {e}")

        await self._save_to_vdb(memory_items=memory_items, timeout=timeout)

    def save_graph_aliases(
        self,
        aliases: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return save_graph_aliases(
            graph_path=self.session_runtime.avatar_path.graph_dir,
            aliases=aliases,
        )
