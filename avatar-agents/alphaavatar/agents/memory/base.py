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
import copy
from abc import abstractmethod
from typing import Any

from livekit.agents.llm import ChatItem

from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.agents.runtime import SessionRuntime
from alphaavatar.agents.utils import TimeStamp, time_str_to_datetime
from alphaavatar.agents.utils.files.work_dirs import SessionPath

from .cache import MemoryCache
from .enum.memory_type import MemoryType
from .schema.memory_item import MemoryItem


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


class MemoryBase(AvatarRuntimePlugin):
    def __init__(
        self,
        *,
        session_runtime: SessionRuntime,
        memory_search_context: int = 3,
        memory_recall_num: int = 10,
        maximum_memory_num: int = 24,
    ) -> None:
        super().__init__()

        self.session_runtime = session_runtime

        # memory config init
        self._memory_search_context = memory_search_context
        self._memory_recall_num = memory_recall_num
        self._maximum_memory_num = maximum_memory_num
        self._memory_cache: dict[str, MemoryCache] = {}

        # memory content init
        self._avatar_memory: list[MemoryItem] = []
        self._user_memory: list[MemoryItem] = []
        self._tool_memory: list[MemoryItem] = []
        self._env_memory: list[MemoryItem] = []

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
    def env_memory(self) -> str:
        memory_list = []
        for item in self._env_memory:
            sub_memory = ""
            sub_memory += f"Timestamp: {item.timestamp}; "
            sub_memory += f"Content: {item.value}"
            memory_list.append(sub_memory.strip())
        return "\n".join(memory_list)

    @property
    def memory_content(self) -> str:
        return "\n".join(
            [
                self.avatar_memory,
                self.user_memory,
                self.tool_memory,
                self.env_memory,
            ]
        )

    @property
    def memory_items(self) -> list[MemoryItem]:
        return self._avatar_memory + self._user_memory + self._tool_memory + self._env_memory

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

    @env_memory.setter
    def env_memory(self, env_memory: list[MemoryItem]) -> None:
        self._env_memory += env_memory
        self._env_memory = deduplicate_keep_latest(self._env_memory)[-self.maximum_memory_num :]

    def add_message(self, *, session_id: str, chat_item: ChatItem):
        if session_id not in self._memory_cache:
            raise ValueError(
                f"Session ID {session_id} not found in memory cache. You need to call 'init_cache' first."
            )

        self._memory_cache[session_id].add_message(chat_item)

    def update_object_id(self, ori_id: str, tgt_id: str) -> None:
        for cache in self._memory_cache.values():
            cache.object_ids = [tgt_id if x == ori_id else x for x in cache.object_ids]

    async def init_cache(
        self,
        *,
        session_id: str,
        session_path: SessionPath,
        object_ids: list[str] | str | None,
        timestamp: TimeStamp,
        memory_type: MemoryType = MemoryType.CONVERSATION,
    ) -> MemoryCache:
        if session_id not in self.memory_cache:
            self.memory_cache[session_id] = MemoryCache(
                timestamp=copy.deepcopy(timestamp),
                session_id=session_id,
                session_path=session_path,
                object_ids=object_ids,
                memory_type=memory_type,
            )
            return self.memory_cache[session_id]
        else:
            raise ValueError(
                f"Session with id '{session_id}' already exists in memory cache. "
                "Please use a unique session_id."
            )

    """Base Op"""

    @abstractmethod
    async def search_by_context(
        self, *, avatar_id: str, session_id: str, chat_context: list[ChatItem]
    ) -> None: ...

    @abstractmethod
    async def search_by_graph_node(
        self,
        *,
        node_key: str | None = None,
        node_query: str | None = None,
        object_ids: list[str] | None = None,
        session_id: str | None = None,
        memory_type: str | None = None,
        node_type: str | None = None,
        max_hops: int = 0,
        top_k: int = 50,
        timeout: float = 3,
    ) -> list[MemoryItem]:
        """
        Search memory items by graph node.

        Supports:
        - node_key exact/canonical/alias lookup
        - node_query semantic graph-node search
        - optional object_ids/session/memory_type/node_type filters
        - optional graph neighbor expansion through data/graph links

        This API is intended for Persona, ENV memory extraction, tools,
        channels, or other plugins that need graph-aware memory retrieval.
        """
        ...

    @abstractmethod
    def save_graph_aliases(
        self,
        aliases: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Save graph aliases for identity/entity merge.

        Example:
            face:local:{session_id}:tmp_1 -> user:{user_id}
            voice:local:{session_id}:speaker_0 -> user:{user_id}

        This only writes graph alias stubs. It should not rewrite VDB directly.
        Query-time alias expansion is handled by search_by_graph_node().
        """
        ...

    @abstractmethod
    async def update(self, *, avatar_id: str, session_id: str | None = None): ...

    @abstractmethod
    async def save(self): ...

    """Runtime Op"""

    async def on_session_start(self, *, context_runtime, **kwargs) -> None:
        primary_user_id = self.session_runtime.primary_user_id
        if not primary_user_id:
            return

        await self.init_cache(
            session_id=self.session_runtime.session_id,
            session_path=self.session_runtime.session_path,
            object_ids=primary_user_id,
            timestamp=context_runtime.timestamp,
        )

    async def on_session_stop(self, *, avatar_id: str, **kwargs) -> None:
        await self.update(avatar_id=avatar_id)
        await self.save()
