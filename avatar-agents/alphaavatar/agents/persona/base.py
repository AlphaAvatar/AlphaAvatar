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

from alphaavatar.agents.avatar.prompting import PersonaPluginsTemplate
from alphaavatar.agents.constants import FACE_THRESHOLD, SPEAKER_THRESHOLD
from alphaavatar.agents.log import logger
from alphaavatar.agents.utils import AvatarTime, NumpyOP, get_user_id

from .cache import FaceCacheBase, PersonaCache, SpeakerCacheBase
from .face import FaceStreamBase
from .profiler import ProfilerBase
from .schema.user_profile import UserProfile, UserRuntimeState
from .speaker import SpeakerStreamBase


class PersonaBase:
    def __init__(
        self,
        *,
        profiler: ProfilerBase,
        speaker_cls: tuple[type[SpeakerStreamBase], type[SpeakerCacheBase]],
        face_cls: tuple[type[FaceStreamBase], type[FaceCacheBase]] | None = None,
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
    def face_stream(self) -> type[FaceStreamBase]:
        return self._face_cls[0]

    @property
    def face_cache(self) -> type[FaceCacheBase]:
        return self._face_cls[1]

    @property
    def persona_cache(self) -> dict[str, PersonaCache]:
        return self._persona_cache

    @property
    def persona_content(self) -> str:
        user_profiles = [
            cache.profile for uid, cache in self.persona_cache.items() if cache.profile is not None
        ]
        return PersonaPluginsTemplate.apply_system_template(user_profiles)

    """Helper Op"""

    def _is_runtime_only_profile(self, profile: UserProfile | None) -> bool:
        """
        A temporary profile created only for session runtime state.

        This commonly happens at session start before speaker/face identity is resolved.
        """
        if profile is None:
            return True

        return (
            profile.details is None
            and profile.speaker_vector is None
            and profile.face_vector is None
            and profile.runtime_state is not None
        )

    def _get_runtime_state(self, uid: str) -> UserRuntimeState | None:
        cache = self.persona_cache.get(uid)
        if cache is None or cache.profile is None:
            return None
        return cache.profile.runtime_state

    def _attach_runtime_state(
        self,
        *,
        profile: UserProfile,
        runtime_state: UserRuntimeState | None,
    ) -> UserProfile:
        if runtime_state is not None:
            profile.runtime_state = runtime_state
        return profile

    """Base Op"""

    def add_message(self, *, user_id: str, chat_item: ChatItem):
        if user_id not in self.persona_cache:
            logger.error(
                f"User ID {user_id} not found in persona cache."
                "You need to call 'init_cache' or 'load_profile' first."
            )
            return

        self.persona_cache[user_id].add_message(chat_item)

    def update_runtime_state(
        self,
        *,
        uid: str | None = None,
        current_timezone: str | None = None,
        timezone_source: str | None = None,
        current_login_time: str | None = None,
        session_id: str | None = None,
        room_type: str | None = None,
    ) -> None:
        target_uid = uid or self._default_user_id

        if target_uid not in self.persona_cache:
            logger.warning(
                f"User ID {target_uid} not found in persona cache. Runtime state update skipped."
            )
            return

        cache = self.persona_cache[target_uid]

        if cache.profile is None:
            cache.profile = UserProfile(runtime_state=UserRuntimeState())

        if cache.runtime_state is None:
            cache.runtime_state = UserRuntimeState()

        state = cache.runtime_state

        if state is None:
            logger.warning(
                f"User ID {target_uid} runtime_state init failed. Runtime state update skipped."
            )
            return

        if state.current_timezone:
            state.last_timezone = state.current_timezone
        if state.current_login_time:
            state.last_login_time = state.current_login_time
        if state.current_session_id:
            state.last_session_id = state.current_session_id
        if state.current_room_type:
            state.last_room_type = state.current_room_type

        state.current_timezone = current_timezone or ""
        state.timezone_source = timezone_source or ""
        state.current_login_time = current_login_time or ""
        state.current_session_id = session_id or ""
        state.current_room_type = room_type or ""

        state.login_count = int(state.login_count or 0) + 1

        logger.info(
            f"[uid: {target_uid}] Persona runtime state updated: "
            f"timezone={current_timezone}, session_id={session_id}, room_type={room_type}"
        )

    async def init_cache(self, *, timestamp: AvatarTime, init_user_id: str):
        if init_user_id not in self.persona_cache:
            self._default_user_id = init_user_id
            self._init_timestamp = timestamp
            user_profile = await self.profiler.load(uid=init_user_id)
            self.persona_cache[init_user_id] = PersonaCache(
                timestamp=timestamp,
                user_profile=user_profile,
                speaker_cache=self.speaker_cache(),
                face_cache=self.face_cache(),
            )
        else:
            logger.error(
                f"User with id '{init_user_id}' already exists in persona cache. "
                "Please use a unique user_id."
            )

    async def load_profile(self, *, uid: str):
        user_profile = await self.profiler.load(uid=uid)

        default_cache = self.persona_cache[self._default_user_id]
        default_runtime_state = (
            default_cache.profile.runtime_state if default_cache.profile is not None else None
        )

        should_replace_default = self._is_runtime_only_profile(default_cache.profile)

        if should_replace_default:
            # Transfer current session runtime state from temporary user to the resolved real user.
            user_profile = self._attach_runtime_state(
                profile=user_profile,
                runtime_state=default_runtime_state,
            )

            # Reuse the original runtime cache object.
            # This preserves speaker_cache, face_cache, messages, retrieval counters,
            # and any other session-local states accumulated before identity resolution.
            default_cache.profile = user_profile

            del self.persona_cache[self._default_user_id]

            self.persona_cache[uid] = default_cache
            self._default_user_id = uid

            logger.info(
                f"User Profile with id '{uid}' loaded and replaced the initial "
                "runtime-only temporary user in persona cache."
            )
            return

        if uid not in self.persona_cache:
            self.persona_cache[uid] = PersonaCache(
                timestamp=self._init_timestamp,
                user_profile=user_profile,
                speaker_cache=self.speaker_cache(),
                face_cache=self.face_cache(),
            )
            logger.info(f"User Profile with id '{uid}' loaded into persona cache.")
        else:
            logger.warning(
                f"User with id '{uid}' already exists in persona cache. "
                "Please use a unique user_id."
            )

    async def save(self, *, uid: str | None = None):
        if uid is not None and uid not in self.persona_cache:
            raise ValueError(
                f"User ID {uid} not found in persona cache. You need to call 'init_cache' first."
            )

        if uid is None:
            persona_tuple = [(uid, cache) for uid, cache in self.persona_cache.items()]
        else:
            persona_tuple = [(uid, self.persona_cache[uid])]

        # save profiler
        for _uid, persona in persona_tuple:
            await self.profiler.save(uid=_uid, persona=persona)

    """Profiler Op"""

    async def update_profile_details(self, *, uid: str | None = None):
        if uid is not None and uid not in self.persona_cache:
            raise ValueError(
                f"User ID {uid} not found in persona cache. You need to call 'init_cache' first."
            )

        if uid is None:
            persona_tuple = [(uid, cache) for uid, cache in self.persona_cache.items()]
        else:
            persona_tuple = [(uid, self.persona_cache[uid])]

        for _uid, persona in persona_tuple:
            await self.profiler.update(uid=_uid, persona=persona)

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

    """Face Op"""

    async def match_face_vector(self, *, face_vector: np.ndarray) -> str | None:
        def _build_gallery(gallery: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
            ids, mats = [], []
            for uid, vec in gallery.items():
                ids.append(uid)
                mats.append(NumpyOP.to_np(vec))
            G = np.stack(mats, axis=0)
            return G, ids

        gallery = {
            uid: cache.face_vector
            for uid, cache in self.persona_cache.items()
            if cache.face_vector is not None
        }
        if len(gallery) == 0:
            return None

        G, ids = _build_gallery(gallery)
        if G.size == 0:
            return None

        p = NumpyOP.l2_normalize(NumpyOP.to_np(face_vector))
        scores = G @ p
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        best_uid = ids[best_idx]

        return best_uid if best_score >= FACE_THRESHOLD else None

    async def update_face_vector(self, *, uid: str, face_vector: np.ndarray | list[float]):
        if uid not in self.persona_cache:
            logger.error(
                f"User ID {uid} not found in persona cache. You need to call 'init_cache' first."
            )
            return

        self.persona_cache[uid].face_vector = NumpyOP.l2_normalize(NumpyOP.to_np(face_vector))
        logger.info(f"User ID {uid} face vector updated in persona cache.")

    async def update_face_attribute(self, *, uid: str, face_attribute: dict[str, Any]):
        if uid not in self.persona_cache:
            logger.error(
                f"User ID {uid} not found in persona cache. You need to call 'init_cache' first."
            )
            return

        self.persona_cache[uid].update_face_profile(face_attribute)
        logger.info(f"User ID {uid} face attribute updated in persona cache.")

    async def insert_face_vector(self, *, face_vector: np.ndarray | list[float]) -> str:
        if self.persona_cache[self._default_user_id].profile is None:
            self.persona_cache[self._default_user_id].profile = UserProfile(
                face_vector=NumpyOP.l2_normalize(NumpyOP.to_np(face_vector))
            )
            return self._default_user_id

        uid = get_user_id()
        user_profile = UserProfile(face_vector=NumpyOP.l2_normalize(NumpyOP.to_np(face_vector)))
        self.persona_cache[uid] = PersonaCache(
            timestamp=self._init_timestamp,
            user_profile=user_profile,
            speaker_cache=self.speaker_cache(),
            face_cache=self.face_cache() if self.face_cache is not None else None,
        )

        logger.info(f"New user profile inserted with face vector uid={uid}")
        return uid
