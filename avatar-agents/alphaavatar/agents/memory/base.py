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
"""Global Memory Abstract Class for Avatar"""

from abc import abstractmethod

from livekit.agents.llm import ChatItem

from alphaavatar.agents.utils import time_str_to_datetime

from .cache import MemoryCache
from .enum.memory_item import MemoryItem
from .enum.memory_type import MemoryType


def deduplicate_keep_latest(items: list[MemoryItem]) -> list[MemoryItem]:
    latest_items: dict[str, MemoryItem] = {}
    for item in items:
        if item.memory_id not in latest_items:
            latest_items[item.memory_id] = item
        else:
            current_time = time_str_to_datetime(item.timestamp)
            existing_time = time_str_to_datetime(latest_items[item.memory_id].timestamp)
            if current_time > existing_time:
                latest_items[item.memory_id] = item

    sorted_items = sorted(latest_items.values(), key=lambda x: time_str_to_datetime(x.timestamp))
    return sorted_items


class MemoryBase:
    def __init__(
        self,
        *,
        memory_search_context: int = 3,
        memory_recall_num: int = 10,
        maximum_memory_num: int = 24,
    ) -> None:
        super().__init__()
        self._memory_search_context = memory_search_context
        self._memory_recall_num = memory_recall_num
        self._maximum_memory_num = maximum_memory_num
        self._memory_cache: dict[str, MemoryCache] = {}

        self._avatar_memory: list[MemoryItem] = []
        self._user_memory: list[MemoryItem] = []
        self._tool_memory: list[MemoryItem] = []

    @property
    def memory_search_context(self) -> int:
        return self._memory_search_context

    @property
    def memory_recall_num(self) -> int:
        return self._memory_recall_num

    @property
    def maximum_memory_num(self) -> int:
        return self._maximum_memory_num

    @property
    def memory_cache(self) -> dict[str, MemoryCache]:
        return self._memory_cache

    @property
    def avatar_memory(self) -> str:
        memory_list = []
        for item in self._avatar_memory:
            sub_memory = ""
            sub_memory += f"Timestamp: {item.timestamp}; "
            sub_memory += f"Content: {item.value}"
            memory_list.append(sub_memory.strip())
        return "\n".join(memory_list)

    @property
    def user_memory(self) -> str:
        memory_list = []
        for item in self._user_memory:
            sub_memory = ""
            sub_memory += f"Timestamp: {item.timestamp}; "
            sub_memory += f"Content: {item.value}"
            memory_list.append(sub_memory.strip())
        return "\n".join(memory_list)

    @property
    def tool_memory(self) -> str:
        memory_list = []
        for item in self._tool_memory:
            sub_memory = ""
            sub_memory += f"Timestamp: {item.timestamp}; "
            sub_memory += f"Content: {item.value}"
            memory_list.append(sub_memory.strip())
        return "\n".join(memory_list)

    @property
    def memory_content(self) -> str:
        # TODO: user memory should be with user profile to put into system prompt.
        return "\n".join([self.avatar_memory, self.user_memory, self.tool_memory])

    @property
    def memory_items(self) -> list[MemoryItem]:
        return self._avatar_memory + self._user_memory + self._tool_memory

    @avatar_memory.setter
    def avatar_memory(self, avatar_memory: list[MemoryItem]) -> None:
        self._avatar_memory += avatar_memory
        self._avatar_memory = deduplicate_keep_latest(self._avatar_memory)[
            -self.maximum_memory_num :
        ]

    @user_memory.setter
    def user_memory(self, user_memory: list[MemoryItem]) -> None:
        self._user_memory += user_memory
        self._user_memory = deduplicate_keep_latest(self._user_memory)[-self.maximum_memory_num :]

    @tool_memory.setter
    def tool_memory(self, tool_memory: list[MemoryItem]) -> None:
        self._tool_memory += tool_memory
        self._tool_memory = deduplicate_keep_latest(self._tool_memory)[-self.maximum_memory_num :]

    def add_message(self, *, session_id: str, chat_item: ChatItem):
        if session_id not in self._memory_cache:
            raise ValueError(
                f"Session ID {session_id} not found in memory cache. You need to call 'init_cache' first."
            )

        self._memory_cache[session_id].add_message(chat_item)

    def update_user_tool_id(self, *, ori_id: str, tgt_id: str):
        for cache in self._memory_cache.values():
            if cache.user_or_tool_id == ori_id:
                cache.user_or_tool_id = tgt_id

    async def init_cache(
        self,
        *,
        session_id: str,
        user_or_tool_id: str,
        memory_type: MemoryType = MemoryType.CONVERSATION,
    ) -> MemoryCache:
        if session_id not in self.memory_cache:
            self.memory_cache[session_id] = MemoryCache(
                session_id=session_id,
                user_or_tool_id=user_or_tool_id,
                memory_type=memory_type,
            )
            return self.memory_cache[session_id]
        else:
            raise ValueError(
                f"Session with id '{session_id}' already exists in memory cache. "
                "Please use a unique session_id."
            )

    @abstractmethod
    async def search_by_context(
        self, *, avatar_id: str, session_id: str, chat_context: list[ChatItem]
    ) -> None: ...

    @abstractmethod
    async def update(self, *, avatar_id: str, session_id: str | None = None): ...

    @abstractmethod
    async def save(self): ...
