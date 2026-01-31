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
import hashlib
import json
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from livekit.agents.job import get_job_context
from livekit.agents.llm import ChatItem
from pydantic import BaseModel, Field

from alphaavatar.agents.avatar import MemoryPluginsTemplate
from alphaavatar.agents.memory import (
    MemoryBase,
    MemoryCache,
    MemoryItem,
    MemoryType,
    VectorRunnerOP,
)
from alphaavatar.agents.utils import format_current_time

from .log import logger
from .memory_op import MemoryDelta, PatchOp, flatten_items, norm_token, rebuild_from_items
from .memory_prompts import MEMORY_EXTRACT_PROMPT
from .runner import QdrantRunner

DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            MEMORY_EXTRACT_PROMPT,
        ),
        (
            "human",
            "NEW TURN TYPE: {type}\n"
            "NEW TURN CONTENT:\n```{message_content}```\n\n"
            "Output only MemoryDelta.\n\n"
            "### WRITING RULES\n"
            "- Each PatchOp.value MUST be exactly one [EVENT]...[/EVENT] card described in the system prompt.\n"
            "- Do NOT write vague summaries. Include tool/component, operation, outcome, and evidence IDs when available.\n"
            "- entities must include high-signal nouns (tool names, ops, error codes, env cues).\n"
            "- topic must be a stable short label (e.g., 'rag indexing', 'web search', 'file storage', 'tool error').\n"
            "- Avoid duplication: only record new events or new details in this turn.\n"
            "- Do not invent details not supported by the content.\n",
        ),
    ]
)


# ===============================
# For Memory Normalization and Dedupe
# ===============================


def _sha12(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _norm_topic(t: str | None) -> str | None:
    if not t:
        return None
    t = " ".join(t.strip().split())
    return t.lower()[:64]


def _norm_entities(ents: list[str]) -> list[str]:
    seen = set()
    out = []
    for e in ents or []:
        e2 = " ".join(str(e).strip().split())
        if not e2:
            continue
        if e2.lower() in seen:
            continue
        seen.add(e2.lower())
        out.append(e2[:48])
    return out[:24]


def _dedupe_key(item_value: str, topic: str | None, entities: list[str]) -> str:
    return _sha12(
        f"{_norm_topic(topic)}|{'|'.join(_norm_entities(entities))}|{item_value.strip()[:800]}"
    )


# ===============================
# For Memory Saving Priority Selection
# ===============================
EVENT_TYPE_RE = re.compile(r"(?im)^\s*type:\s*([a-zA-Z_]+)\s*$")
OUTCOME_RE = re.compile(r"(?im)^\s*outcome:\s*([a-zA-Z_]+)\s*$")
TOPIC_RE = re.compile(r"(?im)^\s*topic:\s*(.+?)\s*$")
ERROR_RE = re.compile(r"(?im)^\s*error:\s*(.+?)\s*$")


def _event_field(value: str, regex: re.Pattern[str]) -> str | None:
    m = regex.search(value or "")
    return m.group(1).strip().lower() if m else None


def _memory_priority(item: "MemoryItem") -> int:
    """
    Higher is more important.
    Works even if value is not an event card (but your prompt aims to always produce one).
    """
    v = (item.value or "").lower()
    t = (item.topic or "").lower()

    etype = _event_field(item.value, EVENT_TYPE_RE) or ""
    outcome = _event_field(item.value, OUTCOME_RE) or ""

    # 1) Hard signals: failures/incidents
    if "outcome: failed" in v or outcome == "failed":
        return 100
    if "outcome: partial" in v or outcome == "partial":
        return 95
    if etype == "incident":
        return 95
    if "error:" in v or _event_field(item.value, ERROR_RE):
        return 92

    # 2) High-value operational memories
    if etype in ("decision", "config_change"):
        return 88
    if etype in ("indexing", "retrieval"):
        return 85
    if t in (
        "rag indexing",
        "tool error",
        "qdrant memory",
        "async debugging",
        "dependency install",
        "gpu detection",
    ):
        return 82

    # 3) Medium: user intent / tasks / important interactions
    if etype in ("interaction", "file_storage", "web_search", "tool_run"):
        return 60

    # 4) Social context: keep but lower priority
    if t in ("social context", "small talk", "chitchat", "chat"):
        # if contains emotion keywords, slightly higher
        if any(
            k in v
            for k in ["tired", "exhausted", "stressed", "anxious", "happy", "excited", "frustrated"]
        ):
            return 45
        return 35

    return 50


def _dedupe_key_for_save(item: "MemoryItem") -> str:
    """
    Dedupe key for storage: topic + entities + normalized value head.
    Keeps it stable across runs.
    """
    topic = (item.topic or "").strip().lower()
    ents = "|".join([e.strip().lower() for e in (item.entities or [])][:12])
    head = (item.value or "").strip().lower()[:800]
    return _sha12(f"{item.object_id}|{topic}|{ents}|{head}")


def _select_by_priority(
    items: list["MemoryItem"],
    *,
    limit: int,
    social_limit: int,
) -> list["MemoryItem"]:
    """
    Select top memories by priority with a cap on social-context items.
    """
    if not items:
        return []

    # Dedupe first
    seen = set()
    deduped: list[MemoryItem] = []
    for it in items:
        k = _dedupe_key_for_save(it)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(it)

    # Sort by priority + newest timestamp (optional)
    deduped.sort(key=lambda x: _memory_priority(x), reverse=True)

    picked: list[MemoryItem] = []
    social_picked = 0

    for it in deduped:
        if len(picked) >= limit:
            break

        t = (it.topic or "").lower()
        if t in ("social context", "small talk", "chitchat", "chat"):
            if social_picked >= social_limit:
                continue
            social_picked += 1

        picked.append(it)

    return picked


class MemmoryInitConfig(BaseModel):
    chat_model: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=0.0)


class MemoryLangchain(MemoryBase):
    def __init__(
        self,
        *,
        memory_search_context: int = 3,
        memory_recall_num: int = 10,
        maximum_memory_num: int = 24,
        memory_init_config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            memory_search_context=memory_search_context,
            memory_recall_num=memory_recall_num,
            maximum_memory_num=maximum_memory_num,
        )

        self._memory_init_config = (
            MemmoryInitConfig(**memory_init_config) if memory_init_config else MemmoryInitConfig()
        )

        llm = ChatOpenAI(
            model=self._memory_init_config.chat_model,
            temperature=self._memory_init_config.temperature,
        )  # type: ignore

        self._delta_llm = llm.with_structured_output(MemoryDelta)
        self._delta_chain = DELTA_PROMPT | self._delta_llm  # ✅ build once
        self._executor = get_job_context().inference_executor

    @property
    def memory_init_config(self) -> MemmoryInitConfig:
        return self._memory_init_config

    async def _safe_ainvoke_delta(
        self,
        *,
        memory_type: MemoryType,
        message_content: str,
        timeout: float = 12.0,
    ) -> MemoryDelta:
        """Robust delta extraction with timeout and fallback."""
        payload = {
            "type": memory_type,
            "message_content": message_content,
        }
        try:
            return await asyncio.wait_for(self._delta_chain.ainvoke(payload), timeout=timeout)  # type: ignore
        except asyncio.TimeoutError:
            logger.warning(f"[Memory] delta extraction timeout (type={memory_type})")
            return MemoryDelta()
        except Exception:
            logger.exception(f"[Memory] delta extraction failed (type={memory_type})")
            return MemoryDelta()

    def _apply_delta(self, avatar_id: str, delta: MemoryDelta, memory_cache: MemoryCache):
        updated_time = format_current_time().time_str
        assistant_memories: list[MemoryItem] = []
        user_memories: list[MemoryItem] = []
        tool_memories: list[MemoryItem] = []

        # local dedupe per update call
        seen_keys: set[str] = set()

        def _maybe_add(
            *,
            bucket: list[MemoryItem],
            object_id: str,
            mem_type: MemoryType,
            item: PatchOp,
        ):
            # normalize
            item.topic = _norm_topic(item.topic)
            item.entities = _norm_entities(item.entities)

            if not norm_token(item.value):
                return

            dk = _dedupe_key(item.value, item.topic, item.entities)
            if dk in seen_keys:
                return
            seen_keys.add(dk)

            bucket.append(
                MemoryItem(
                    updated=True,
                    session_id=memory_cache.session_id,
                    object_id=object_id,
                    value=item.value,
                    entities=item.entities,
                    topic=item.topic,
                    timestamp=updated_time,
                    memory_type=mem_type,
                )
            )

        # assistant memory
        for item in delta.assistant_memory_entries:
            _maybe_add(
                bucket=assistant_memories,
                object_id=avatar_id,
                mem_type=MemoryType.Avatar,
                item=item,
            )

        # user or tool memory
        if memory_cache.type == MemoryType.CONVERSATION:
            for item in delta.user_or_tool_memory_entries:
                _maybe_add(
                    bucket=user_memories,
                    object_id=memory_cache.user_or_tool_id,
                    mem_type=MemoryType.CONVERSATION,
                    item=item,
                )
        else:
            for item in delta.user_or_tool_memory_entries:
                _maybe_add(
                    bucket=tool_memories,
                    object_id=memory_cache.user_or_tool_id,
                    mem_type=MemoryType.TOOLS,
                    item=item,
                )

        return assistant_memories, user_memories, tool_memories

    async def search_by_context(
        self, *, avatar_id: str, session_id: str, chat_context: list[ChatItem], timeout: float = 3
    ) -> None:
        """Search for relevant memories based on the query."""
        context_str = MemoryPluginsTemplate.apply_search_template(
            chat_context[-getattr(self, "memory_search_context", 3) :], filter_roles=["system"]
        )

        if not context_str:
            return

        if self.memory_cache[session_id].type == MemoryType.CONVERSATION:
            json_data = {
                "op": VectorRunnerOP.search_by_context,
                "param": {
                    "context_str": context_str,
                    "avatar_id": avatar_id,
                    "user_id": self.memory_cache[session_id].user_or_tool_id,
                    "top_k": self.memory_recall_num,
                },
            }
            json_data = json.dumps(json_data).encode()
        else:
            # TODO: we will implement the part in the future
            raise NotImplementedError

        result = await asyncio.wait_for(
            self._executor.do_inference(QdrantRunner.INFERENCE_METHOD, json_data),
            timeout=timeout,
        )

        if result is None:
            logger.warning("Memory [search_by_context] falied, result is None!")
            return

        data: dict[str, Any] = json.loads(result.decode())

        # Avatar Memory
        if data.get("avatar_memory_items", None):
            self.avatar_memory = rebuild_from_items(data["avatar_memory_items"])

        # User Memory
        if data.get("user_rmemory_items", None):
            self.user_memory = rebuild_from_items(data["user_rmemory_items"])

        if data.get("error", None):
            logger.warning(f"Memory [search_by_context] err: {data['error']}")

    async def update(self, *, avatar_id: str, session_id: str | None = None):
        """Update the memory database with the cached messages."""
        if session_id is not None and session_id not in self.memory_cache:
            raise ValueError(
                f"Session ID {session_id} not found in memory cache. You need to call 'init_cache' first."
            )

        memory_tuple = (
            [(sid, cache) for sid, cache in self.memory_cache.items()]
            if session_id is None
            else [(session_id, self.memory_cache[session_id])]
        )

        # ✅ accumulate instead of overwrite
        all_assistant: list[MemoryItem] = []
        all_user: list[MemoryItem] = []
        all_tool: list[MemoryItem] = []

        for _sid, cache in memory_tuple:
            chat_context = cache.messages
            if not chat_context:
                logger.info(f"[sid: {_sid}] Memory message is empty, UPDATE skip!")
                continue  # ✅ important

            message_content: str = MemoryPluginsTemplate.apply_update_template(
                chat_context, cache.type
            )

            delta: MemoryDelta = await self._safe_ainvoke_delta(
                memory_type=cache.type,
                message_content=message_content,
                timeout=12.0,
            )

            assistant_memories, user_memories, tool_memories = self._apply_delta(
                avatar_id, delta, cache
            )

            all_assistant.extend(assistant_memories)
            all_user.extend(user_memories)
            all_tool.extend(tool_memories)

        self.avatar_memory = all_assistant
        self.user_memory = all_user
        self.tool_memory = all_tool

    async def save(self, timeout: float = 3):
        # 1) Collect updated MemoryItem objects (not dict yet)
        updated_items: list[MemoryItem] = [item for item in self.memory_items if item.updated]

        if not updated_items:
            logger.info("Avatar Memory SAVE skip!")
            return

        # 2) Split buckets by memory_type (optional but recommended)
        avatar_items = [x for x in updated_items if x.memory_type == MemoryType.Avatar]
        user_items = [x for x in updated_items if x.memory_type == MemoryType.CONVERSATION]
        tool_items = [x for x in updated_items if x.memory_type == MemoryType.TOOLS]

        # 3) Apply priority selection with quotas
        # You can tune these numbers; idea: keep incidents/decisions, allow small amount of social.
        max_total = getattr(self, "maximum_memory_num", 24)

        # Per bucket limits (sum can exceed max_total; we'll cap again later)
        avatar_selected = _select_by_priority(
            avatar_items, limit=min(10, max_total), social_limit=1
        )
        user_selected = _select_by_priority(user_items, limit=min(10, max_total), social_limit=2)
        tool_selected = _select_by_priority(tool_items, limit=min(10, max_total), social_limit=0)

        selected = avatar_selected + user_selected + tool_selected

        # 4) Global cap (final)
        selected.sort(key=lambda x: _memory_priority(x), reverse=True)
        selected = selected[:max_total]

        # 5) Convert to dict for storage
        memory_items: list[dict] = flatten_items(selected)

        if not memory_items:
            logger.info("Memory SAVE skip after priority filtering (no items selected).")
            return

        json_data = {
            "op": VectorRunnerOP.save,
            "param": {"memory_items": memory_items},
        }

        try:
            result = await asyncio.wait_for(
                self._executor.do_inference(
                    QdrantRunner.INFERENCE_METHOD, json.dumps(json_data).encode()
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Memory SAVE timeout!")
            return

        if result is None:
            logger.warning("Memory SAVE failed, result is None!")
            return

        payload = json.loads(result.decode())
        if payload.get("error") is not None:
            logger.warning(f"Memory SAVE failed, because: {payload['error']}")
            return

        payload.pop("error", None)
        logger.info(f"Memory SAVE success: {payload}")
