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
from typing import Any

from livekit.agents.llm import ChatItem
from mem0 import AsyncMemoryClient

from alphaavatar.agents.memory import MemoryBase, apply_memory_template


def apply_client_memory_list(results: list[dict[str, Any]]) -> list:
    memory_list = []
    for entry in results:
        sub_memory = ""
        if "metadata" in entry and "time_str" in entry["metadata"]:
            sub_memory += f"Timestamp: {entry['metadata']['time_str']}; "
        sub_memory += f"Content: {entry['memory']}"
        memory_list.append(sub_memory.strip())
    return memory_list


def apply_memory_list(results: dict[str, Any]) -> list:
    return [entry["memory"] for entry in results["results"]]


# TODO: customize memory extracting prompt
class Mem0ClientMemory(MemoryBase):
    def __init__(
        self,
        *,
        avater_name: str,
        avatar_id: str,
        memory_search_context: int = 3,
        memory_recall_session: int = 100,
        maximum_memory_items: int = 24,
        **kwargs,
    ) -> None:
        super().__init__(
            avater_name=avater_name,
            avatar_id=avatar_id,
            memory_search_context=memory_search_context,
            memory_recall_session=memory_recall_session,
            maximum_memory_items=maximum_memory_items,
        )

        self._client = AsyncMemoryClient()

    @property
    def client(self) -> AsyncMemoryClient:
        return self._client

    async def search(self, *, session_id: str, chat_context: list[ChatItem]):
        """Search for relevant memories based on the query."""
        query_str = apply_memory_template(
            chat_context[-getattr(self, "memory_search_context", 3) :], filter_roles=["system"]
        )

        agent_memory_filter = {"AND": [{"agent_id": self.avatar_id}, {"run_id": "*"}]}
        user_or_tool_memory_filter = {
            "AND": [{"user_id": self.memory_cache[session_id].user_or_tool_id}, {"run_id": "*"}]
        }

        if isinstance(self.client, AsyncMemoryClient):
            agent_results, user_or_tool_results = await asyncio.gather(
                self.client.search(query=query_str, version="v2", filters=agent_memory_filter),
                self.client.search(
                    query=query_str, version="v2", filters=user_or_tool_memory_filter
                ),
            )
            self.agent_memory = apply_client_memory_list(agent_results)
            self.user_memory = apply_client_memory_list(user_or_tool_results)
        else:
            agent_results, user_or_tool_results = await asyncio.gather(
                self.client.search(
                    query=query_str, limit=self.memory_recall_session, filters=agent_memory_filter
                ),
                self.client.search(
                    query=query_str,
                    limit=self.memory_recall_session,
                    filters=user_or_tool_memory_filter,
                ),
            )
            self.agent_memory = apply_memory_list(agent_results)
            self.user_memory = apply_memory_list(user_or_tool_results)

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

            await self.client.add(
                agent_id=self.avatar_id,
                user_id=cache.user_or_tool_id,
                run_id=cache.session_id,
                messages=messages,
                metadata=cache.metadata,
            )
