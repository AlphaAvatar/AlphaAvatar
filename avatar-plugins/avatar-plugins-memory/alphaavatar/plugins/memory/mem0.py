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
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from mem0 import AsyncMemory, AsyncMemoryClient

from alphaavatar.agents.memory import MemoryBase


class Memory(MemoryBase):
    def __init__(
        self,
        *,
        avater_name: str,
        avatar_id: str,
        memory_token_length: NotGivenOr[int | None] = NOT_GIVEN,
        memory_recall_session: NotGivenOr[int | None] = NOT_GIVEN,
        client: NotGivenOr[AsyncMemory | AsyncMemoryClient | None] = NOT_GIVEN,
    ) -> None:
        super().__init__(
            avater_name=avater_name,
            avatar_id=avatar_id,
            memory_token_length=memory_token_length,
            memory_recall_session=memory_recall_session,
        )

        self._client = client or AsyncMemory()

    @property
    def client(self) -> AsyncMemoryClient | AsyncMemory:
        return self._client

    async def search(self, *, query: str) -> str:
        """Search for relevant memories based on the query.

        Args:
            query (str): _description_

        Returns:
            _type_: _description_
        """
        relevant_memories = self.client.search(
            query, user_id=self.avater_name, limit=self.memory_recall_session
        )
        if isinstance(self.client, AsyncMemoryClient):
            memories_str = "\n".join(f"- {entry['memory']}" for entry in relevant_memories)
        else:
            memories_str = "\n".join(
                f"- {entry['memory']}" for entry in relevant_memories["results"]
            )
        return memories_str

    async def update(self, *, session_id: str | None = None):
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
            messages = cache.convert_to_message_list()
            if not messages:
                continue

            self.client.add(
                agent_id=self.avatar_id,
                user_id=cache.user_id,
                run_id=cache.session_id,
                messages=messages,
                metadata=cache.metadata,
            )
