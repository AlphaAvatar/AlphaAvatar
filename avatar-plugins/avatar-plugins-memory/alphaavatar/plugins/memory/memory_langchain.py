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
from .memory_op import MemoryDelta, flatten_items, norm_token, rebuild_from_items
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
            "CONVERSATION CONTENT ({type}):\n```{message_content}```\n\n"
            "Output only MemoryDelta (list of PatchOps, If nothing changes, return an empty list).\n"
            """
### WRITING RULES
- Each `PatchOp.value` should be a clear, concise English sentence or short paragraph.
- `entities` should list key nouns or named entities (users, tools, places, topics).
- `topic` should be a short label like `"property purchase"`, `"AI code debugging"`, `"automotive interests"`, or `"social context"`.
- Avoid duplication of previous memory content; only record new or changed insights.
- Do not invent details not supported by the conversation.""",
        ),
    ]
)


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
        self._executor = get_job_context().inference_executor

    @property
    def memory_init_config(self) -> MemmoryInitConfig:
        return self._memory_init_config

    async def _aextract_delta(self, message_content: str, memory_type: MemoryType) -> MemoryDelta:
        """Ask the LLM to generate patch ops relative to the current profile."""
        chain = DELTA_PROMPT | self._delta_llm
        return await chain.ainvoke({"type": memory_type, "message_content": message_content})  # type: ignore

    def _apply_delta(self, avatar_id: str, delta: MemoryDelta, memory_cache: MemoryCache):
        updated_time = format_current_time().time_str
        assistant_memories: list[MemoryItem] = []
        user_memories: list[MemoryItem] = []
        tool_memories: list[MemoryItem] = []

        # apply assistant memory
        for item in delta.assistant_memory_entries:
            if norm_token(item.value):
                assistant_memories.append(
                    MemoryItem(
                        updated=True,
                        session_id=memory_cache.session_id,
                        object_id=avatar_id,
                        value=item.value,
                        entities=item.entities,
                        topic=item.topic,
                        timestamp=updated_time,
                        memory_type=MemoryType.Avatar,
                    )
                )

        # apply user or tool memory
        if memory_cache.type == MemoryType.CONVERSATION:
            for item in delta.user_or_tool_memory_entries:
                if norm_token(item.value):
                    user_memories.append(
                        MemoryItem(
                            updated=True,
                            session_id=memory_cache.session_id,
                            object_id=memory_cache.user_or_tool_id,
                            value=item.value,
                            entities=item.entities,
                            topic=item.topic,
                            timestamp=updated_time,
                            memory_type=MemoryType.CONVERSATION,
                        )
                    )
        else:
            for item in delta.user_or_tool_memory_entries:
                if norm_token(item.value):
                    tool_memories.append(
                        MemoryItem(
                            updated=True,
                            session_id=memory_cache.session_id,
                            object_id=memory_cache.user_or_tool_id,
                            value=item.value,
                            entities=item.entities,
                            topic=item.topic,
                            timestamp=updated_time,
                            memory_type=MemoryType.TOOLS,
                        )
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
        """Update the memory database with the cached messages.
        If session_id is None, update all sessions in the memory cache.
        """

        if session_id is not None and session_id not in self.memory_cache:
            raise ValueError(
                f"Session ID {session_id} not found in memory cache. You need to call 'init_cache' first."
            )

        if session_id is None:
            memory_tuple = [(sid, cache) for sid, cache in self.memory_cache.items()]
        else:
            memory_tuple = [(session_id, self.memory_cache[session_id])]

        for _sid, cache in memory_tuple:
            chat_context = cache.messages
            if not chat_context:
                logger.info(f"[sid: {_sid}] Memory message is empty, UPDATE skip!")

            message_content: str = MemoryPluginsTemplate.apply_update_template(
                chat_context, cache.type
            )
            delta: MemoryDelta = await self._aextract_delta(message_content, cache.type)
            assistant_memories, user_memories, tool_memories = self._apply_delta(
                avatar_id, delta, cache
            )
            self.avatar_memory = assistant_memories
            self.user_memory = user_memories
            self.tool_memory = tool_memories

    async def save(self, timeout: float = 3):
        memory_items: list[dict] = flatten_items(
            [item for item in self.memory_items if item.updated]
        )

        if len(memory_items) == 0:
            logger.info("Avatar Memory SAVE skip!")
            return

        json_data = {
            "op": VectorRunnerOP.save,
            "param": {
                "memory_items": memory_items,
            },
        }
        json_data = json.dumps(json_data).encode()
        result = await asyncio.wait_for(
            self._executor.do_inference(QdrantRunner.INFERENCE_METHOD, json_data),
            timeout=timeout,
        )

        if result is None:
            logger.warning("Memory SAVE falied, result is None!")
        else:
            result = json.loads(result.decode())
            if result["error"] is not None:
                logger.warning(f"Memory SAVE falied, because: {result['error']}")
            else:
                del result["error"]
                logger.info(f"Memory SAVE success: {result}")
