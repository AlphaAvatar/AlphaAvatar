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
from __future__ import annotations

from typing import TYPE_CHECKING

from livekit.agents.llm import ChatItem, ChatMessage

if TYPE_CHECKING:
    from .profiler import UserProfileBase


class PersonaCache:
    def __init__(
        self,
        *,
        user_profile: UserProfileBase,
        speech_profile: UserProfileBase,
        visual_profile: UserProfileBase,
        current_retrieval_times: int = 0,
    ):
        self._user_profile = user_profile
        self._speech_profile = speech_profile
        self._visual_profile = visual_profile
        self._current_retrieval_times = current_retrieval_times

        self._messages: list[ChatItem] = []

    @property
    def user_profile(self):
        return self._user_profile

    @property
    def speech_profile(self):
        return self._speech_profile

    @property
    def visual_profile(self):
        return self._visual_profile

    @property
    def retrieval_times(self):
        return self._current_retrieval_times

    @property
    def messages(self):
        return self._messages

    @user_profile.setter
    def user_profile(self, user_profile: UserProfileBase):
        self._user_profile = user_profile

    def add_message(self, message: ChatItem):
        """Add a new message to the cache."""
        if isinstance(message, ChatMessage) and message.role in ("user", "assistant"):
            self._messages.append(message)
            self._messages.sort(key=lambda x: x.created_at)
