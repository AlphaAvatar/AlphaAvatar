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

from alphaavatar.agents.utils import AvatarTime

if TYPE_CHECKING:
    from .profiler import DetailsBase, UserProfile


class PersonaCache:
    def __init__(
        self,
        *,
        timestamp: AvatarTime,
        user_profile: UserProfile,
        speech_profile: UserProfile,
        visual_profile: UserProfile,
        current_retrieval_times: int = 0,
    ):
        self._timestamp = timestamp
        self._user_profile = user_profile
        self._speech_profile = speech_profile
        self._visual_profile = visual_profile
        self._current_retrieval_times = current_retrieval_times

        self._messages: list[ChatItem] = []

    @property
    def time(self) -> str:
        return self._timestamp.time_str

    @property
    def user_profile(self) -> UserProfile:
        return self._user_profile

    @property
    def user_profile_details(self) -> DetailsBase:
        return self._user_profile.details

    @property
    def user_profile_timestamp(self) -> dict[str, str]:
        return self._user_profile.timestamp

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

    @user_profile_details.setter
    def user_profile_details(self, profile_details: DetailsBase):
        self._user_profile.details = profile_details

    @user_profile_timestamp.setter
    def user_profile_timestamp(self, timestamp: dict):
        self._user_profile.timestamp.update(timestamp)

    def add_message(self, message: ChatItem):
        """Add a new message to the cache."""
        if isinstance(message, ChatMessage) and message.role in ("user", "assistant"):
            self._messages.append(message)
            self._messages.sort(key=lambda x: x.created_at)
