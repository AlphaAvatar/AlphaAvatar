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
from enum import Enum

from livekit.agents.llm import ChatItem, ChatMessage, ChatRole


def apply_memory_template(
    messages: list[ChatItem], *, filter_roles: list[ChatRole] | None = None
) -> str:
    """Apply the memory template with the given keyword arguments."""
    if filter_roles is None:
        filter_roles = []
    memory_strings = []
    for msg in messages:
        if isinstance(msg, ChatMessage):
            role = msg.role
            if role in filter_roles:
                continue

            msg_str = msg.text_content  # TODO: Handle different content types more robustly
            memory_strings.append(f"### {role}:\n{msg_str}")

    return "\n\n".join(memory_strings)


def apply_message_template(messages: list[ChatItem]) -> list[dict]:
    """Apply the memory template with the given keyword arguments."""
    message_list = []
    for msg in messages:
        if isinstance(msg, ChatMessage):
            role = msg.role
            msg_str = msg.text_content  # TODO: Handle different content types more robustly
            message_list.append({"role": role, "content": str(msg_str)})

    return message_list


class MemoryType(str, Enum):
    CONVERSATION = "conversation"
    TOOLS = "tools"


class MemoryCache:
    """It is used to temporarily store the short-term memory content of the Avatar's current conversation session.
    When the session ends, it will be updated to the memory database."""

    def __init__(
        self,
        timestamp: dict,
        session_id: str | None = None,
        user_or_tool_id: str | None = None,
        memory_type: MemoryType = MemoryType.CONVERSATION,
    ):
        self._user_or_tool_id = user_or_tool_id
        self._session_id = session_id

        self._metadata = {"type": memory_type, "topic": "", **timestamp}
        self._messages: list[ChatItem] = []

    @property
    def metadata(self) -> dict:
        """Get the metadata of the memory cache."""
        return self._metadata

    @property
    def user_or_tool_id(self) -> str | None:
        """Get the user/tool ID associated with the memory cache."""
        return self._user_or_tool_id

    @property
    def session_id(self) -> str | None:
        """Get the session ID associated with the memory cache."""
        return self._session_id

    def add_message(self, message: ChatItem):
        """Add a new message to the cache."""
        if isinstance(message, ChatMessage) and message.role in ("user", "assistant"):
            self._messages.append(message)
            self._messages.sort(key=lambda x: x.created_at)

    def convert_to_memory_string(self) -> str:
        """Convert the cached messages to a string format suitable for memory storage."""
        memory_str = apply_memory_template(self._messages)
        return memory_str

    def convert_to_message_list(self) -> list[dict]:
        """Convert the cached messages to a list of message dicts suitable for memory storage."""
        messages = apply_message_template(self._messages)
        return messages
