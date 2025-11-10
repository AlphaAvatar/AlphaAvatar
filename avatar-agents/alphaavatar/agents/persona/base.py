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
from typing import Any

import numpy as np
from livekit.agents.llm import ChatItem

from alphaavatar.agents.avatar import PersonaPluginsTemplate
from alphaavatar.agents.constants import SPEAKER_THRESHOLD
from alphaavatar.agents.log import logger
from alphaavatar.agents.utils import AvatarTime, NumpyOP, get_user_id

from .cache import PersonaCache, SpeakerCacheBase
from .enum.user_profile import UserProfile
from .profiler import ProfilerBase
from .speaker import SpeakerStreamBase


class PersonaBase:
    def __init__(
        self,
        *,
        profiler: ProfilerBase,
        speaker_cls: tuple[type[SpeakerStreamBase], type[SpeakerCacheBase]],
        face_cls: tuple[type[SpeakerStreamBase], type[SpeakerCacheBase]],
        maximum_retrieval_times: int = 3,
    ):
        self._profiler = profiler
        self._speaker_cls = speaker_cls
        self._face_cls = face_cls

        self._maximum_retrieval_times = maximum_retrieval_times

        self._persona_cache: dict[str, PersonaCache] = {}

    @property
    def default_uid(self) -> str:
        return self._default_user_id

    @property
    def profiler(self) -> ProfilerBase:
        return self._profiler

    @property
    def speaker_stream(self) -> type[SpeakerStreamBase]:
        return self._speaker_cls[0]

    @property
    def speaker_cache(self) -> type[SpeakerCacheBase]:
        return self._speaker_cls[1]

    @property
    def persona_cache(self) -> dict[str, PersonaCache]:
        return self._persona_cache

    @property
    def persona_content(self) -> str:
        user_profiles = [
            cache.profile for uid, cache in self.persona_cache.items() if cache.profile is not None
        ]
        return PersonaPluginsTemplate.apply_profile_template(user_profiles)

    """Base Op"""

    def add_message(self, *, user_id: str, chat_item: ChatItem):
        if user_id not in self.persona_cache:
            logger.error(
                f"User ID {user_id} not found in perona cache."
                "You need to call 'init_cache' or 'load_profile' first."
            )
            return

        self.persona_cache[user_id].add_message(chat_item)

    async def init_cache(self, *, timestamp: AvatarTime, init_user_id: str):
        if init_user_id not in self.persona_cache:
            self._default_user_id = init_user_id
            self._init_timestamp = timestamp
            user_profile = await self.profiler.load(uid=init_user_id)
            self.persona_cache[init_user_id] = PersonaCache(
                timestamp=timestamp,
                user_profile=user_profile,
                speaker_cache=self.speaker_cache(),
            )
        else:
            logger.error(
                f"User with id '{init_user_id}' already exists in perona cache. "
                "Please use a unique user_id."
            )

    async def load_profile(self, *, uid: str):
        user_profile = await self.profiler.load(uid=uid)
        if self.persona_cache[self._default_user_id].profile is None:
            del self.persona_cache[self._default_user_id]
            self.persona_cache[uid] = PersonaCache(
                timestamp=self._init_timestamp,
                user_profile=user_profile,
                speaker_cache=self.speaker_cache(),
            )
            self._default_user_id = uid
            logger.info(
                f"User Profile with id '{uid}' loaded and "
                "replaced the initial temporary user in perona cache."
            )
        else:
            if uid not in self.persona_cache:
                self.persona_cache[uid] = PersonaCache(
                    timestamp=self._init_timestamp,
                    user_profile=user_profile,
                    speaker_cache=self.speaker_cache(),
                )
                logger.info(f"User Profile with id '{uid}' loaded into perona cache.")
            else:
                logger.warning(
                    f"User with id '{uid}' already exists in perona cache. "
                    "Please use a unique user_id."
                )

    async def save(self, *, uid: str | None = None):
        if uid is not None and uid not in self.persona_cache:
            raise ValueError(
                f"User ID {uid} not found in persona cache. You need to call 'init_cache' first."
            )

        if uid is None:
            perona_tuple = [(uid, cache) for uid, cache in self.persona_cache.items()]
        else:
            perona_tuple = [(uid, self.persona_cache[uid])]

        # save profiler
        for _uid, perona in perona_tuple:
            await self.profiler.save(uid=_uid, perona=perona)

    """Profiler Op"""

    async def update_profile_details(self, *, uid: str | None = None):
        if uid is not None and uid not in self.persona_cache:
            raise ValueError(
                f"User ID {uid} not found in persona cache. You need to call 'init_cache' first."
            )

        if uid is None:
            perona_tuple = [(uid, cache) for uid, cache in self.persona_cache.items()]
        else:
            perona_tuple = [(uid, self.persona_cache[uid])]

        for _uid, perona in perona_tuple:
            await self.profiler.update(uid=_uid, perona=perona)

    """Speaker Op"""

    async def match_speaker_vector(self, *, speaker_vector: np.ndarray) -> str | None:
        """Match and retrieve the user ID based on the given speaker vector."""

        def _build_gallery(gallery: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
            ids, mats = [], []
            for uid, vec in gallery.items():
                ids.append(uid)
                mats.append(NumpyOP.to_np(vec))
            G = np.stack(mats, axis=0)  # (M, D)
            return G, ids

        gallery = {
            uid: cache.speaker_vector
            for uid, cache in self.persona_cache.items()
            if cache.speaker_vector is not None
        }
        if len(gallery) == 0:
            return None

        G, ids = _build_gallery(gallery)
        if G.size == 0:
            return None

        p = NumpyOP.l2_normalize(NumpyOP.to_np(speaker_vector))
        scores = G @ p  # (M,)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        best_uid = ids[best_idx]

        return best_uid if best_score >= SPEAKER_THRESHOLD else None

    async def update_speaker_vector(self, *, uid: str, speaker_vector: np.ndarray | list[float]):
        if uid not in self.persona_cache:
            logger.error(
                f"User ID {uid} not found in persona cache. You need to call 'init_cache' first."
            )
            return

        if self.persona_cache[uid].speaker_vector is None:
            logger.error(
                f"User ID {uid} has no speaker vector in persona cache. You need to call 'insert_speaker' first."
            )
            return

        self.persona_cache[uid].speaker_vector = NumpyOP.l2_normalize(NumpyOP.to_np(speaker_vector))
        logger.info(f"User ID {uid} speaker vector updated in persona cache.")

    async def update_speaker_attribute(self, *, uid: str, speaker_attribute: dict[str, Any]):
        if uid not in self.persona_cache:
            logger.error(
                f"User ID {uid} not found in persona cache. You need to call 'init_cache' first."
            )
            return

        self.persona_cache[uid].update_speaker_profile(speaker_attribute)
        logger.info(f"User ID {uid} speaker attribute updated in persona cache.")

    async def insert_speaker_vector(self, *, speaker_vector: np.ndarray | list[float]):
        # TODO: hadle multiple users
        if self.persona_cache[self._default_user_id].profile is None:
            self.persona_cache[self._default_user_id].profile = UserProfile(
                speaker_vector=NumpyOP.l2_normalize(NumpyOP.to_np(speaker_vector))
            )
        else:
            uid = get_user_id()
            user_profile = UserProfile(
                speaker_vector=NumpyOP.l2_normalize(NumpyOP.to_np(speaker_vector))
            )
            self.persona_cache[uid] = PersonaCache(
                timestamp=self._init_timestamp,
                user_profile=user_profile,
                speaker_cache=self.speaker_cache(),
            )
