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
from livekit.agents.llm import ChatItem, ChatMessage, FunctionCall, FunctionCallOutput

from .enum.memory_type import MemoryType


class MemoryCache:
    """It is used to temporarily store the short-term memory content of the Avatar's current conversation session.
    When the session ends, it will be updated to the memory database."""

    def __init__(
        self,
        session_id: str,
        user_or_tool_id: str,
        memory_type: MemoryType = MemoryType.CONVERSATION,
    ):
        self._user_or_tool_id = user_or_tool_id
        self._session_id = session_id
        self._memory_type = memory_type
        self._messages: list[ChatItem] = []

    @property
    def user_or_tool_id(self) -> str:
        """Get the user/tool ID associated with the memory cache."""
        return self._user_or_tool_id

    @property
    def session_id(self) -> str:
        """Get the session ID associated with the memory cache."""
        return self._session_id

    @property
    def type(self) -> MemoryType:
        return self._memory_type

    @property
    def messages(self) -> list[ChatItem]:
        return self._messages

    @user_or_tool_id.setter
    def user_or_tool_id(self, id: str):
        self.user_or_tool_id = id

    def add_message(self, message: ChatItem):
        """Add a new message to the cache."""
        if isinstance(message, ChatMessage) and message.role in ("user", "assistant"):
            self._messages.append(message)
        elif isinstance(message, FunctionCall) or isinstance(message, FunctionCallOutput):
            self._messages.append(message)

        self._messages.sort(key=lambda x: x.created_at)
