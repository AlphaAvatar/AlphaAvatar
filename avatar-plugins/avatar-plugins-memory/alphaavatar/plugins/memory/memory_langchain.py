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
import os
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
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
from alphaavatar.agents.utils import format_current_time
from alphaavatar.agents.utils.files.work_dirs import UserPath

from .log import logger
from .memory_markdown import save_memory_items_to_markdown
from .memory_op import MemoryDelta, PatchOp, flatten_items, norm_token, rebuild_from_items
from .memory_prompts import (
    CONVERSATION_MEMORY_EXTRACT_PROMPT,
    TOOL_MEMORY_EXTRACT_PROMPT,
)

CONVERSATION_DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            CONVERSATION_MEMORY_EXTRACT_PROMPT,
        ),
        (
            "human",
            "NEW TURN TYPE: {type}\n"
            "NEW TURN CONTENT:\n```{message_content}```\n\n"
            "Output only `MemoryDelta`.\n\n"
            "### WRITING RULES\n"
            "- Each user_or_tool_memory_entries PatchOp.value MUST be exactly one [MEMORY]...[/MEMORY] card for conversation memory.\n"
            "- Each assistant_memory_entries PatchOp.value MUST be exactly one [MEMORY]...[/MEMORY] card for avatar memory.\n"
            "- summary must preserve user intent, assistant response, and any continuing context.\n"
            "- Do NOT write raw tool logs, request IDs, file paths, actions, or next_steps unless absolutely necessary.\n"
            "- If tools were used, describe only the user-facing result at a high level.\n"
            "- entities must include high-signal nouns.\n"
            "- topic must be a stable short label.\n"
            "- Avoid duplication: only record new conversational facts or new details in this turn.\n"
            "- Do not invent details not supported by the content.\n",
        ),
    ]
)

TOOL_DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            TOOL_MEMORY_EXTRACT_PROMPT,
        ),
        (
            "human",
            "NEW TURN TYPE: {type}\n"
            "NEW TURN CONTENT:\n```{message_content}```\n\n"
            "Output only `MemoryDelta`.\n\n"
            "### TOOL EVENT GATE\n"
            "- Before writing any memory, decide whether the content contains an explicit tool/system operation.\n"
            "- A valid tool event requires explicit evidence such as FunctionCall, FunctionCallOutput, tool_calls, function_call, ToolMessage, tool output, file read/write/save/index/generation, search/retrieval/indexing/download/scrape, explicit tool error, retry, fallback, or config update.\n"
            "- ChatMessage, normal assistant replies, normal user messages, ImageContent, VideoFrame, visual input, sampled frames, audio/transcript text, and latency metrics are NOT tool events by themselves.\n"
            "- Assistant visual reasoning over attached frames is not artifact_generation and not a tool memory.\n"
            "- Runtime metrics such as TTS/STT/LLM latency are not tool memories unless they show an explicit incident, failure, retry, fallback, or config change.\n"
            "- Do not infer an internal tool/component from multimodal understanding.\n"
            "- Do not invent components such as visual_analysis_module, vision_tool, image_analyzer, or multimodal_module unless they explicitly appear in the content.\n"
            "- If there is no explicit tool event, output MemoryDelta with both lists empty.\n\n"
            "### WRITING RULES\n"
            "- Each user_or_tool_memory_entries PatchOp.value MUST be exactly one [EVENT]...[/EVENT] card for tool memory.\n"
            "- Each assistant_memory_entries PatchOp.value MUST be exactly one [EVENT]...[/EVENT] card for avatar memory derived from tool events.\n"
            "- Include concrete tool/component, operation, outcome, and relevant sanitized details.\n"
            "- Include evidence IDs only when actually present.\n"
            "- entities must include high-signal nouns such as tool names, operations, error identifiers, or artifact types.\n"
            "- topic must be a stable short label.\n"
            "- Avoid duplication: only record new tool events or new details in this turn.\n"
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
KIND_RE = re.compile(r"(?im)^\s*kind:\s*([a-zA-Z_]+)\s*$")
SUMMARY_RE = re.compile(r"(?ims)^\s*summary:\s*(.+?)\s*$")
CONTEXT_RE = re.compile(r"(?ims)^\s*context:\s*(.+?)\s*$")


def _memory_field(value: str, regex: re.Pattern[str]) -> str | None:
    m = regex.search(value or "")
    return m.group(1).strip() if m else None


def _event_field(value: str, regex: re.Pattern[str]) -> str | None:
    m = regex.search(value or "")
    return m.group(1).strip().lower() if m else None


def _memory_priority(item: "MemoryItem") -> int:
    """
    Higher is more important.
    Supports both:
    - [EVENT] cards for tool memory
    - [MEMORY] cards for conversation/avatar memory
    """
    v = (item.value or "").lower()
    t = (item.topic or "").lower()

    etype = _event_field(item.value, EVENT_TYPE_RE) or ""
    outcome = _event_field(item.value, OUTCOME_RE) or ""
    kind = (_memory_field(item.value, KIND_RE) or "").strip().lower()

    # 1) Hard signals: failures/incidents
    if "outcome: failed" in v or outcome == "failed":
        return 100
    if "outcome: partial" in v or outcome == "partial":
        return 95
    if etype == "incident":
        return 95
    if "error:" in v or _event_field(item.value, ERROR_RE):
        return 92

    # 2) Avatar memory is usually high-value global memory
    if item.memory_type == MemoryType.Avatar:
        if kind == "avatar":
            return 90
        if etype in ("decision", "config_change"):
            return 88
        return 86

    # 3) Tool-side operational memories
    if item.memory_type == MemoryType.TOOLS:
        if etype in ("decision", "config_change"):
            return 88
        if etype in ("indexing", "retrieval", "web_search", "tool_run", "artifact_generation"):
            return 82
        if t in (
            "rag indexing",
            "tool error",
            "qdrant memory",
            "async debugging",
            "dependency install",
            "gpu detection",
            "memory prompt inspection",
            "tool memory policy",
        ):
            return 80
        return 70

    # 4) Conversation memories
    if item.memory_type == MemoryType.CONVERSATION:
        if kind == "conversation":
            if t in (
                "response preference",
                "user response preference",
                "memory prompt design",
                "alphaavatar architecture",
                "social context",
            ):
                return 72

            # If it contains explicit preference/emotion/project context, slightly higher
            if any(
                k in v
                for k in [
                    "prefers",
                    "preference",
                    "short and direct",
                    "concise",
                    "building",
                    "redesigning",
                    "stressed",
                    "tired",
                    "excited",
                    "frustrated",
                ]
            ):
                return 68

            return 60

    # 5) Fallbacks
    if t in ("social context", "small talk", "chitchat", "chat"):
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


class MemoryInitConfig(BaseModel):
    openai_model: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=0.0)


class MemoryLangchain(MemoryBase):
    def __init__(
        self,
        *,
        user_path: UserPath,
        memory_search_context: int = 3,
        memory_recall_num: int = 10,
        maximum_memory_num: int = 24,
        memory_init_config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            user_path=user_path,
            memory_search_context=memory_search_context,
            memory_recall_num=memory_recall_num,
            maximum_memory_num=maximum_memory_num,
        )

        self._memory_init_config = (
            MemoryInitConfig(**memory_init_config) if memory_init_config else MemoryInitConfig()
        )

        llm = ChatOpenAI(
            model=self._memory_init_config.openai_model,
            temperature=self._memory_init_config.temperature,
        )  # type: ignore

        self._delta_llm = llm.with_structured_output(MemoryDelta)
        self._conversation_delta_chain = CONVERSATION_DELTA_PROMPT | self._delta_llm
        self._tool_delta_chain = TOOL_DELTA_PROMPT | self._delta_llm
        self._executor = get_job_context().inference_executor

    @property
    def memory_init_config(self) -> MemoryInitConfig:
        return self._memory_init_config

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

    async def _safe_ainvoke_conversation_delta(
        self,
        *,
        message_content: str,
        timeout: float = 12.0,
    ) -> MemoryDelta:
        payload = {
            "type": MemoryType.CONVERSATION,
            "message_content": message_content,
        }
        try:
            return await asyncio.wait_for(
                self._conversation_delta_chain.ainvoke(payload), timeout=timeout
            )  # type: ignore
        except asyncio.TimeoutError:
            logger.warning("[Memory] conversation delta extraction timeout")
            return MemoryDelta()
        except Exception:
            logger.exception("[Memory] conversation delta extraction failed")
            return MemoryDelta()

    async def _safe_ainvoke_tool_delta(
        self,
        *,
        message_content: str,
        timeout: float = 12.0,
    ) -> MemoryDelta:
        payload = {
            "type": MemoryType.TOOLS,
            "message_content": message_content,
        }
        try:
            return await asyncio.wait_for(self._tool_delta_chain.ainvoke(payload), timeout=timeout)  # type: ignore
        except asyncio.TimeoutError:
            logger.warning("[Memory] tool delta extraction timeout")
            return MemoryDelta()
        except Exception:
            logger.exception("[Memory] tool delta extraction failed")
            return MemoryDelta()

    def _apply_delta_to_bucket(
        self,
        *,
        avatar_id: str,
        delta: MemoryDelta,
        memory_cache: MemoryCache,
        user_or_tool_memory_type: MemoryType,
    ):
        updated_time = format_current_time().time_str
        assistant_memories: list[MemoryItem] = []
        target_memories: list[MemoryItem] = []

        seen_keys: set[str] = set()

        def _maybe_add(
            *,
            bucket: list[MemoryItem],
            object_id: str,
            mem_type: MemoryType,
            item: PatchOp,
        ):
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

        for item in delta.assistant_memory_entries:
            _maybe_add(
                bucket=assistant_memories,
                object_id=avatar_id,
                mem_type=MemoryType.Avatar,
                item=item,
            )

        for item in delta.user_or_tool_memory_entries:
            _maybe_add(
                bucket=target_memories,
                object_id=memory_cache.user_or_tool_id,
                mem_type=user_or_tool_memory_type,
                item=item,
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
                "avatar_id": avatar_id,
                "user_or_tool_id": self.memory_cache[session_id].user_or_tool_id,
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

        if data.get("error", None):
            logger.warning(f"Memory [search_by_context] err: {data['error']}")

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
                            message_content=message_content,
                            timeout=30.0,
                        ),
                        self._safe_ainvoke_tool_delta(
                            message_content=message_content,
                            timeout=30.0,
                        ),
                    )
                else:
                    conversation_delta = await self._safe_ainvoke_conversation_delta(
                        message_content=message_content,
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
        # 1. Collect updated MemoryItem objects (not dict yet)
        updated_items: list[MemoryItem] = [item for item in self.memory_items if item.updated]

        if not updated_items:
            logger.info("Avatar Memory SAVE skip!")
            return

        # 2. Split buckets by memory_type (optional but recommended)
        avatar_items = [x for x in updated_items if x.memory_type == MemoryType.Avatar]
        user_items = [x for x in updated_items if x.memory_type == MemoryType.CONVERSATION]
        tool_items = [x for x in updated_items if x.memory_type == MemoryType.TOOLS]

        # 3. Apply priority selection with quotas
        ## 3.1 You can tune these numbers; idea: keep incidents/decisions, allow small amount of social.
        max_total = getattr(self, "maximum_memory_num", 24)

        ## 3.2 Per bucket limits (sum can exceed max_total; we'll cap again later)
        avatar_selected = _select_by_priority(
            avatar_items, limit=min(10, max_total), social_limit=1
        )
        user_selected = _select_by_priority(user_items, limit=min(10, max_total), social_limit=2)
        tool_selected = _select_by_priority(tool_items, limit=min(10, max_total), social_limit=0)

        selected = avatar_selected + user_selected + tool_selected

        # 4. Global cap (final)
        selected.sort(key=lambda x: _memory_priority(x), reverse=True)
        selected = selected[:max_total]

        # 5. Convert to dict for storage
        memory_items: list[dict] = flatten_items(selected)

        if not memory_items:
            logger.info("Memory SAVE skip after priority filtering (no items selected).")
            return

        ## 5.1 Save to local .md file for backup/debug
        try:
            md_result = save_memory_items_to_markdown(
                avatar_memory_path=self._avatar_memory_path,
                session_memory_path=self.working_dir,
                memory_items=memory_items,
            )
            logger.info(f"Memory local markdown backup success: {md_result}")
        except Exception as e:
            logger.warning(f"Memory local markdown backup failed: {e}")

        ## 5.2 Save to VDB via runner
        json_data = {
            "op": VectorRunnerOP.save,
            "param": {"memory_items": memory_items},
        }

        try:
            result = await asyncio.wait_for(
                self._executor.do_inference(self.inference_method, json.dumps(json_data).encode()),
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
