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

from abc import ABC, abstractmethod

from livekit.agents.llm import ChatItem

from .cache import MemoryCache, MemoryType


class MemoryBase(ABC):
    def __init__(
        self,
        *,
        avater_name: str,
        avatar_id: str,
        memory_search_length: int = 2,
        memory_recall_session: int = 100,
    ) -> None:
        super().__init__()
        self._avatar_name = avater_name
        self._avatar_id = avatar_id
        self._memory_search_length = memory_search_length
        self._memory_recall_session = memory_recall_session
        self._memory_cache: dict[str, MemoryCache] = {}

        self._agent_memory: str | None = None
        self._user_memory: str | None = None
        self._tool_memory: str | None = None

    @property
    def avater_name(self) -> str:
        return self._avatar_name

    @property
    def avatar_id(self) -> str:
        return self._avatar_id

    @property
    def memory_search_length(self) -> int:
        return self._memory_search_length

    @property
    def memory_recall_session(self) -> int:
        return self._memory_recall_session

    @property
    def memory_cache(self) -> dict[str, MemoryCache]:
        return self._memory_cache

    @property
    def agent_memory(self) -> str | None:
        return self._agent_memory

    @agent_memory.setter
    def agent_memory(self, memory: str) -> None:
        self._agent_memory = memory

    @property
    def user_memory(self) -> str | None:
        return self._user_memory

    @user_memory.setter
    def user_memory(self, memory: str) -> None:
        self._user_memory = memory

    def init_cache(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        memory_type: MemoryType = MemoryType.CONVERSATION,
    ) -> MemoryCache:
        if session_id not in self._memory_cache:
            self._memory_cache[session_id] = MemoryCache(
                session_id=session_id,
                user_id=user_id,
                memory_type=memory_type,
            )
        return self._memory_cache[session_id]

    @abstractmethod
    async def search(
        self, *, session_id: str, chat_context: list[ChatItem], chat_item: ChatItem
    ): ...

    @abstractmethod
    async def update(self, *, session_id: str | None = None): ...

    def add(self, *, session_id: str, chat_item: ChatItem):
        if session_id not in self._memory_cache:
            raise ValueError(
                f"Session ID {session_id} not found in memory cache. You need to call 'init_cache' first."
            )

        self._memory_cache[session_id].add_message(chat_item)
