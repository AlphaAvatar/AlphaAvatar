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
from livekit.agents.llm import ChatItem

from alphaavatar.agents.utils import format_current_time


def apply_memory_template(messages: list[ChatItem], **kwargs) -> str:
    """Apply the memory template with the given keyword arguments."""
    memory_strings = []
    for msg in messages:
        role = msg.role
        msg_str = ""
        content: list[dict] = msg.content
        for item in content:
            if isinstance(item, str):
                msg_str += item + "\n"
            else:  # TODO: Handle different content types more robustly
                continue

        memory_strings.append(f"### {role}:\n{msg_str.strip()}")

    return "\n\n".join(memory_strings)


class MemoryCache:
    """It is used to temporarily store the short-term memory content of the Avatar's current conversation session.
    When the session ends, it will be updated to the memory database."""

    def __init__(
        self,
        memory_type: str = "conversation",
    ):
        self._metadata = {"type": memory_type}
        self._metadata.update(format_current_time())
        self._messages: list[ChatItem] = []

    def add_message(self, message: ChatItem):
        """Add a new message to the cache."""
        self._messages.append(message)

    def convert_to_memory_string(self) -> str:
        """Convert the cached messages to a string format suitable for memory storage."""
        return apply_memory_template(self._messages)
