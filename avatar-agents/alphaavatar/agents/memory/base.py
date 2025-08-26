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
from livekit.agents.types import NOT_GIVEN, NotGivenOr

from .cache import MemoryCache, MemoryType


class MemoryBase(ABC):
    def __init__(
        self,
        *,
        avater_name: str,
        memory_id: str,
        memory_token_length: NotGivenOr[int | None] = NOT_GIVEN,
        memory_recall_session: NotGivenOr[int | None] = NOT_GIVEN,
    ) -> None:
        super().__init__()
        self._avatar_name = avater_name
        self._memory_id = memory_id
        self._memory_token_length = memory_token_length
        self._memory_recall_session = memory_recall_session
        self._memory_cache: dict[str, MemoryCache] = {}

    @property
    def avater_name(self) -> str:
        return self._avatar_name

    @property
    def memory_id(self) -> str:
        return self._memory_id

    @property
    def memory_recall_session(self) -> NotGivenOr[int | None]:
        return self._memory_recall_session

    @property
    def memory_cache(self) -> dict[str, MemoryCache]:
        return self._memory_cache

    def init_cache(
        self, *, session_id: str, memory_type: MemoryType = MemoryType.CONVERSATION
    ) -> MemoryCache:
        if session_id not in self._memory_cache:
            self._memory_cache[session_id] = MemoryCache(
                memory_type=memory_type,
                session_id=session_id,
            )
        return self._memory_cache[session_id]

    @abstractmethod
    async def search(self, *, query: str): ...

    @abstractmethod
    async def update(self, *, session_id: str | None = None): ...

    def add(self, *, session_id: str, chat_item: ChatItem):
        if session_id not in self._memory_cache:
            raise ValueError(
                f"Session ID {session_id} not found in memory cache. You need to call 'init_cache' first."
            )

        self._memory_cache[session_id].add_message(chat_item)
