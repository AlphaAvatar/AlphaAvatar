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

from .cache import PersonaCache
from .identifier import IdentifierBase
from .profiler import ProfilerBase
from .recognizer import RecognizerBase


class PersonaBase:
    def __init__(
        self,
        *,
        profiler: ProfilerBase,
        identifier: IdentifierBase,
        recognizer: RecognizerBase,
        maximum_retrieval_times: int = 3,
    ):
        self._profiler = profiler
        self._identifier = identifier
        self._recognizer = recognizer

        self._maximum_retrieval_times = maximum_retrieval_times

        self._persona_cache: dict[str, PersonaCache] = {}

    @property
    def profiler(self) -> ProfilerBase:
        return self._profiler

    @property
    def identifier(self) -> IdentifierBase:
        return self._identifier

    @property
    def recognizer(self) -> RecognizerBase:
        return self._recognizer

    @property
    def persona_cache(self) -> dict[str, PersonaCache]:
        return self._persona_cache

    def init_cache(self, *, user_id: str) -> PersonaCache:
        if user_id not in self.persona_cache:
            user_profile = self.profiler.load(user_id)
            # speech_profile = self.identifier.load(user_id)
            # visual_profile = self.recognizer.load(user_id)

            self.persona_cache[user_id] = PersonaCache(
                user_profile=user_profile,
                speech_profile=None,  # type: ignore
                visual_profile=None,  # type: ignore
            )
            return self.persona_cache[user_id]
        else:
            raise ValueError(
                f"User with id '{user_id}' already exists in perona cache. "
                "Please use a unique user_id."
            )

    def add(self, *, user_id: str, chat_item: ChatItem):
        if user_id not in self._persona_cache:
            raise ValueError(
                f"User ID {user_id} not found in perona cache. You need to call 'init_cache' first."
            )

        self._persona_cache[user_id].add_message(chat_item)

    async def update(self, *, user_id: str | None = None):
        """"""
        if user_id is not None and user_id not in self.persona_cache:
            raise ValueError(
                f"User ID {user_id} not found in persona cache. You need to call 'init_cache' first."
            )

        if user_id is None:
            perona_tuple = [(uid, cache) for uid, cache in self.persona_cache.items()]
        else:
            perona_tuple = [(user_id, self.persona_cache[user_id])]

        update_clss_list = [self.recognizer, self.identifier, self.profiler]
        for update_clss in update_clss_list:
            if update_clss and hasattr(update_clss, "update") and callable(update_clss.update):
                for _uid, perona in perona_tuple:
                    await update_clss.update(perona)
