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

from alphaavatar.agents.utils.op_utils import deduplicate_keep_latest

from .cache import MemoryCache, MemoryType


class MemoryBase:
    def __init__(
        self,
        *,
        avater_name: str,
        avatar_id: str,
        memory_search_context: int = 3,
        memory_recall_session: int = 100,
        maximum_memory_items: int = 24,
    ) -> None:
        super().__init__()
        self._avatar_name = avater_name
        self._avatar_id = avatar_id
        self._memory_search_context = memory_search_context
        self._memory_recall_session = memory_recall_session
        self._maximum_memory_items = maximum_memory_items
        self._memory_cache: dict[str, MemoryCache] = {}

        self._agent_memory: list[str] = []
        self._user_memory: list[str] = []
        self._tool_memory: list[str] = []

    @property
    def avater_name(self) -> str:
        return self._avatar_name

    @property
    def avatar_id(self) -> str:
        return self._avatar_id

    @property
    def memory_search_context(self) -> int:
        return self._memory_search_context

    @property
    def memory_recall_session(self) -> int:
        return self._memory_recall_session

    @property
    def maximum_memory_items(self) -> int:
        return self._maximum_memory_items

    @property
    def memory_cache(self) -> dict[str, MemoryCache]:
        return self._memory_cache

    @property
    def agent_memory(self) -> str:
        return "\n".join(self._agent_memory)

    @property
    def user_memory(self) -> str:
        return "\n".join(self._user_memory)

    @property
    def tool_memory(self) -> str:
        return "\n".join(self._tool_memory)

    @property
    def memory_content(self) -> str:
        # TODO: user memory should be with user profile to put into system prompt.
        return "\n".join([self.agent_memory, self.user_memory, self.tool_memory])

    @agent_memory.setter
    def agent_memory(self, agent_memory: list[str]) -> None:
        combined = self._agent_memory + agent_memory
        self._agent_memory = deduplicate_keep_latest(combined)[-self.maximum_memory_items :]

    @user_memory.setter
    def user_memory(self, user_memory: list[str]) -> None:
        combined = self._user_memory + user_memory
        self._user_memory = deduplicate_keep_latest(combined)[-self.maximum_memory_items :]

    @tool_memory.setter
    def tool_memory(self, tool_memory: list[str]) -> None:
        combined = self._tool_memory + tool_memory
        self._tool_memory = deduplicate_keep_latest(combined)[-self.maximum_memory_items :]

    def init_cache(
        self,
        *,
        timestamp: dict,
        session_id: str,
        user_or_tool_id: str | None = None,
        memory_type: MemoryType = MemoryType.CONVERSATION,
    ) -> MemoryCache:
        if session_id not in self._memory_cache:
            self._memory_cache[session_id] = MemoryCache(
                timestamp=timestamp,
                session_id=session_id,
                user_or_tool_id=user_or_tool_id,
                memory_type=memory_type,
            )
            return self._memory_cache[session_id]
        else:
            raise ValueError(
                f"Session with id '{session_id}' already exists in memory cache. "
                "Please use a unique session_id."
            )

    @abstractmethod
    async def search(self, *, session_id: str, chat_context: list[ChatItem]): ...

    @abstractmethod
    async def update(self, *, session_id: str | None = None): ...

    def add(self, *, session_id: str, chat_item: ChatItem):
        if session_id not in self._memory_cache:
            raise ValueError(
                f"Session ID {session_id} not found in memory cache. You need to call 'init_cache' first."
            )

        self._memory_cache[session_id].add_message(chat_item)
