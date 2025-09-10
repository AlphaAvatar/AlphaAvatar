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
from abc import abstractmethod

from livekit.agents.llm import ChatItem, ChatMessage
from pydantic import BaseModel


class UserProfileBase(BaseModel):
    @classmethod
    def apply_update_template(cls, chat_context: list[ChatItem]):
        """Apply the profile update template with the given keyword arguments."""
        memory_strings = []
        for msg in chat_context:
            if isinstance(msg, ChatMessage):
                role = msg.role
                # TODO: Handle different content types more robustly
                if role not in ["user", "assistant"]:
                    continue

                msg_str = msg.text_content
                memory_strings.append(f"### {role}:\n{msg_str}")

        return "\n\n".join(memory_strings)


class ProfilerBase:
    def __init__(self):
        pass

    @abstractmethod
    def load(self, user_id: str) -> UserProfileBase: ...

    @abstractmethod
    def search(self, profile: UserProfileBase): ...

    @abstractmethod
    async def update(
        self, profile: UserProfileBase, chat_context: list[ChatItem]
    ) -> UserProfileBase: ...

    @abstractmethod
    async def save(self, user_id: str, profile: UserProfileBase) -> None: ...
