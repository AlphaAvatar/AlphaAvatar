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

import numpy as np
from livekit.agents.llm import ChatItem

from alphaavatar.agents.log import logger
from alphaavatar.agents.template import PersonaPluginsTemplate
from alphaavatar.agents.utils import AvatarTime, NumpyOP

from .cache import PersonaCache
from .enum.user_profile import UserProfile
from .profiler import ProfilerBase
from .recognizer import RecognizerBase
from .speaker import SpeakerStreamBase


class PersonaBase:
    def __init__(
        self,
        *,
        profiler: ProfilerBase,
        speaker_stream: type[SpeakerStreamBase],
        recognizer: RecognizerBase,
        maximum_retrieval_times: int = 3,
        speaker_threshold: float = 0.75,
    ):
        self._profiler = profiler
        self._speaker_stream = speaker_stream
        self._recognizer = recognizer

        self._maximum_retrieval_times = maximum_retrieval_times
        self._speaker_threshold = speaker_threshold

        self._persona_cache: dict[str, PersonaCache] = {}

    @property
    def profiler(self) -> ProfilerBase:
        return self._profiler

    @property
    def speaker_stream(self) -> type[SpeakerStreamBase]:
        return self._speaker_stream

    @property
    def recognizer(self) -> RecognizerBase:
        return self._recognizer

    @property
    def persona_cache(self) -> dict[str, PersonaCache]:
        return self._persona_cache

    @property
    def persona_content(self) -> str:
        user_profiles = [
            cache.profile for uid, cache in self.persona_cache.items() if cache.profile is not None
        ]
        return PersonaPluginsTemplate.apply_profile_template(user_profiles)

    def add_message(self, *, user_id: str, chat_item: ChatItem):
        if user_id not in self._persona_cache:
            raise ValueError(
                f"User ID {user_id} not found in perona cache. You need to call 'init_cache' first."
            )

        self._persona_cache[user_id].add_message(chat_item)

    async def init_cache(self, *, timestamp: AvatarTime, init_user_id: str) -> PersonaCache:
        if init_user_id not in self.persona_cache:
            self._init_user_id = init_user_id
            user_profile = await self.profiler.load(user_id=init_user_id)
            self.persona_cache[init_user_id] = PersonaCache(
                timestamp=timestamp,
                user_profile=user_profile,
            )
            return self.persona_cache[init_user_id]
        else:
            raise ValueError(
                f"User with id '{init_user_id}' already exists in perona cache. "
                "Please use a unique user_id."
            )

    async def match_speaker(self, *, speaker_vector: np.ndarray) -> str | None:
        """Match and retrieve the user ID based on the given speaker vector."""

        def _build_gallery(gallery: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
            ids, mats = [], []
            for sid, vec in gallery.items():
                ids.append(sid)
                mats.append(NumpyOP.to_np(vec))
            G = np.stack(mats, axis=0)  # (M, D)
            return G, ids

        gallery = {
            uid: cache.speaker_vector
            for uid, cache in self.persona_cache.items()
            if cache.speaker_vector is not None
        }
        G, ids = _build_gallery(gallery)
        if G.size == 0:
            return None

        p = NumpyOP.np_l2_normalize(NumpyOP.to_np(speaker_vector))
        scores = G @ p  # (M,)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        best_uid = ids[best_idx]

        return best_uid if best_score >= self._speaker_threshold else None

    async def update_profiler(self, *, user_id: str | None = None):
        if user_id is not None and user_id not in self.persona_cache:
            raise ValueError(
                f"User ID {user_id} not found in persona cache. You need to call 'init_cache' first."
            )

        if user_id is None:
            perona_tuple = [(uid, cache) for uid, cache in self.persona_cache.items()]
        else:
            perona_tuple = [(user_id, self.persona_cache[user_id])]

        for _uid, perona in perona_tuple:
            await self.profiler.update(perona=perona)

    async def update_speaker(self, *, user_id: str, speaker_vector: np.ndarray):
        if user_id not in self.persona_cache:
            logger.error(
                f"User ID {user_id} not found in persona cache. You need to call 'init_cache' first."
            )
            return

        # self.persona_cache[user_id].profile.speaker_vector = vector

    async def insert_speaker(self, *, speaker_vector: np.ndarray):
        if self.persona_cache[self._init_user_id].profile is None:
            self.persona_cache[self._init_user_id].profile = UserProfile(
                speaker_vector=NumpyOP.np_l2_normalize(speaker_vector)
            )
            return
        else:
            raise NotImplementedError

    async def save(self, *, user_id: str | None = None):
        if user_id is not None and user_id not in self.persona_cache:
            raise ValueError(
                f"User ID {user_id} not found in persona cache. You need to call 'init_cache' first."
            )

        if user_id is None:
            perona_tuple = [(uid, cache) for uid, cache in self.persona_cache.items()]
        else:
            perona_tuple = [(user_id, self.persona_cache[user_id])]

        # save profiler
        for _uid, perona in perona_tuple:
            await self.profiler.save(user_id=_uid, perona=perona)
