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

from livekit.agents import llm
from livekit.agents.types import NOT_GIVEN, NotGivenOr

from .cache import MemoryCache


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

        self._memory_cache = MemoryCache()

    @property
    def avater_name(self) -> str:
        return self._avatar_name

    @property
    def memory_recall_session(self) -> NotGivenOr[int | None]:
        return self._memory_recall_session

    @abstractmethod
    async def search(self, *, query: str): ...

    @abstractmethod
    async def add(self, *, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage):
        """"""

    @abstractmethod
    async def update(
        self,
    ): ...
