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

import numpy as np
from livekit.agents.llm import ChatItem, ChatMessage

from alphaavatar.agents.utils import AvatarTime, NumpyOP

from .enum.user_profile import DetailsBase, UserProfile

SPEAKER_BETA = 0.95


class PersonaCache:
    def __init__(
        self,
        *,
        timestamp: AvatarTime,
        user_profile: UserProfile,
        current_retrieval_times: int = 0,
    ):
        self._timestamp = timestamp
        self._user_profile = user_profile
        self._current_retrieval_times = current_retrieval_times

        self._messages: list[ChatItem] = []

    @property
    def time(self) -> str:
        return self._timestamp.time_str

    @property
    def retrieval_times(self):
        return self._current_retrieval_times

    @property
    def messages(self):
        return self._messages

    @property
    def profile(self) -> UserProfile | None:
        if self._user_profile.details is not None or self._user_profile.speaker_vector is not None:
            return self._user_profile
        else:
            return None

    @property
    def profile_details(self) -> DetailsBase | None:
        return self._user_profile.details

    @property
    def profile_details_dump_value(self) -> dict:
        if self.profile_details:
            json_dump = self.profile_details.model_dump()
            json_dump_value = {}
            for key in json_dump:
                val = json_dump[key]
                if val is None:
                    continue

                if isinstance(val, dict):
                    json_dump_value[key] = val["value"]
                elif isinstance(val, list):
                    json_dump_value[key] = [x["value"] for x in val if isinstance(x, dict)]

            return json_dump_value
        else:
            return {}

    @property
    def speaker_vector(self) -> np.ndarray | None:
        return self._user_profile.speaker_vector

    @profile.setter
    def profile(self, profile: UserProfile):
        self._user_profile = profile

    @profile_details.setter
    def profile_details(self, profile_details: DetailsBase):
        self._user_profile.details = profile_details

    @speaker_vector.setter
    def speaker_vector(self, vector: np.ndarray):
        if self.profile is None:
            raise ValueError("Cannot set speaker_vector before profile is set.")

        current = getattr(self._user_profile, "speaker_vector", None)
        if current is None:
            self._user_profile.speaker_vector = vector
        else:
            if current.shape != vector.shape:
                raise ValueError(
                    f"speaker_vector shape mismatch: {current.shape} vs {vector.shape}"
                )
            self._user_profile.speaker_vector = NumpyOP.l2_normalize(
                SPEAKER_BETA * current + (1 - SPEAKER_BETA) * vector
            )

    def add_message(self, message: ChatItem):
        """Add a new message to the cache."""
        if isinstance(message, ChatMessage) and message.role in ("user", "assistant"):
            self._messages.append(message)
            self._messages.sort(key=lambda x: x.created_at)
