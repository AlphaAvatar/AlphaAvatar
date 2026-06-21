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
from alphaavatar.agents.constants import FACE_MATCH_THRESHOLD, SPEAKER_MATCH_THRESHOLD
from alphaavatar.agents.log import debug_every, logger
from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.agents.runtime.session_runtime import ParticipantInfo, SessionRuntime
from alphaavatar.agents.utils import NumpyOP

from .cache import FaceCacheBase, PersonaCache, SpeakerCacheBase
from .face import FaceStreamBase
from .profiler import ProfilerBase
from .schema.user_profile import UserProfile, UserRuntimeState
from .speaker import SpeakerStreamBase


class PersonaBase(AvatarRuntimePlugin):
    def __init__(
        self,
        *,
        session_runtime: SessionRuntime,
        profiler: ProfilerBase,
        speaker_cls: tuple[type[SpeakerStreamBase], type[SpeakerCacheBase]],
        face_cls: tuple[type[FaceStreamBase], type[FaceCacheBase]] | None = None,
        maximum_retrieval_times: int = 3,
    ):
        self.session_runtime = session_runtime

        self._profiler = profiler
        self._speaker_cls = speaker_cls
        self._face_cls = face_cls

        self._maximum_retrieval_times = maximum_retrieval_times

        self._persona_cache: dict[str, PersonaCache] = {}

        # UIDs loaded from persistent persona storage.
        # The initial default uid is not necessarily a real user.
        self._resolved_uids: set[str] = set()

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

    def _ensure_runtime_state(self, *, user_profile: UserProfile) -> UserRuntimeState:
        if user_profile.runtime_state is None:
            user_profile.runtime_state = UserRuntimeState()
        return user_profile.runtime_state

    def _is_resolved_uid(self, uid: str) -> bool:
        return uid in self._resolved_uids

    def _update_runtime_state(
        self,
        *,
        participant: ParticipantInfo,
        user_profile: UserProfile,
    ) -> None:
        """Update the runtime state of the user profile based on the current timestamp and session information."""
        state = self._ensure_runtime_state(user_profile=user_profile)

        if state.current_timezone:
            state.last_timezone = state.current_timezone
        if state.current_login_time:
            state.last_login_time = state.current_login_time
        if state.current_session_id:
            state.last_session_id = state.current_session_id
        if state.current_room_type:
            state.last_room_type = state.current_room_type

        state.current_timezone = participant.timestamp.timezone or ""
        state.current_login_time = participant.timestamp.time_str or ""
        state.current_session_id = self.session_runtime.session_id
        state.current_room_type = participant.room_type or ""

        state.login_count = int(state.login_count or 0) + 1

    def _can_merge_profiles(
        self,
        *,
        session_profile: UserProfile | None,
        loaded_profile: UserProfile | None,
    ) -> bool:
        """
        Decide whether a session-collected temporary profile can be merged into
        a loaded persistent profile.

        This is evidence-based, not mode-based:
        - Missing fields can be filled.
        - Same-modality conflicts should not be merged automatically.
        """
        if session_profile is None:
            return True

        if loaded_profile is None:
            return True

        if session_profile.speaker_vector is not None and loaded_profile.speaker_vector is not None:
            session_vec = NumpyOP.l2_normalize(NumpyOP.to_np(session_profile.speaker_vector))
            loaded_vec = NumpyOP.l2_normalize(NumpyOP.to_np(loaded_profile.speaker_vector))
            score = float(session_vec @ loaded_vec)

            if score < SPEAKER_MATCH_THRESHOLD:
                logger.warning(
                    "Reject profile merge because speaker vectors conflict score=%.4f",
                    score,
                )
                return False

        if session_profile.face_vector is not None and loaded_profile.face_vector is not None:
            session_vec = NumpyOP.l2_normalize(NumpyOP.to_np(session_profile.face_vector))
            loaded_vec = NumpyOP.l2_normalize(NumpyOP.to_np(loaded_profile.face_vector))
            score = float(session_vec @ loaded_vec)

            if score < FACE_MATCH_THRESHOLD:
                logger.warning(
                    "Reject profile merge because face vectors conflict score=%.4f",
                    score,
                )
                return False

        return True

    def _merge_profile_for_identity_resolution(
        self,
        *,
        loaded_profile: UserProfile,
        session_profile: UserProfile | None,
    ) -> UserProfile:
        """
        Merge session-collected signals into a loaded persistent profile.

        Persistent loaded profile has priority.
        Session profile only fills missing fields.
        """
        if session_profile is not None:
            if loaded_profile.details is None and session_profile.details is not None:
                loaded_profile.details = session_profile.details

            if loaded_profile.speaker_vector is None and session_profile.speaker_vector is not None:
                loaded_profile.speaker_vector = session_profile.speaker_vector

            if loaded_profile.face_vector is None and session_profile.face_vector is not None:
                loaded_profile.face_vector = session_profile.face_vector

        return loaded_profile

    """Base Op"""

    def add_message(self, *, chat_item: ChatItem):
        for cache_uid in self.persona_cache:
            self.persona_cache[cache_uid].add_message(chat_item)

    async def load_profile(self, *, uid: str):
        if uid in self.persona_cache:
            logger.warning(
                f"User with id '{uid}' already exists in persona cache. "
                "Please use a unique user_id."
            )

        # Load (The new participant will load before the profile loads.)
        participant = self.session_runtime.get_participant(user_id=uid)
        user_profile = await self.profiler.load(uid=uid, work_dir=self.session_runtime.avatar_path)

        if participant is None and (user_profile is None or user_profile.is_empty):
            logger.error(
                f"No participant and Profile found for uid '{uid}' in session. Please check!"
            )
            return

        # Init persona cache
        if participant:
            if user_profile is None or user_profile.is_empty:
                logger.info(f"User Profile with id '{uid}' init into persona cache.")
            else:
                logger.info(f"User Profile with id '{uid}' loaded into persona cache.")

            self._update_runtime_state(participant=participant, user_profile=user_profile)
            self.persona_cache[uid] = PersonaCache(
                participant=participant,
                user_profile=user_profile,
                speaker_cache=self.speaker_cache(),
                face_cache=self.face_cache(),
            )
            return

        persona_chace_keys = list(self.persona_cache.keys())
        for cache_uid in persona_chace_keys:
            cache = self.persona_cache[cache_uid]
            cache_participant = cache.participant
            cache_profile = cache.profile

            if self._can_merge_profiles(
                session_profile=cache_profile,
                loaded_profile=user_profile,
            ):
                self.session_runtime.update_participant_user_id(
                    participant_id=cache_participant.participant_id, user_id=uid
                )
                self._update_runtime_state(participant=cache_participant, user_profile=user_profile)
                user_profile = self._merge_profile_for_identity_resolution(
                    session_profile=cache_profile,
                    loaded_profile=user_profile,
                )

                cache.participant = self.session_runtime.get_participant(user_id=uid)
                cache.profile = user_profile

                old_uid = cache_uid
                del self.persona_cache[cache_uid]

                self.persona_cache[uid] = cache

                logger.info(
                    f"User Profile with id '{uid}' loaded and merged with unresolved "
                    f"default persona cache old_default_uid='{old_uid}'."
                )
                return

        logger.warning(f"User Profile with id '{uid}' loaded and merged falied. Please check!")

    async def save(self, *, uid: str | None = None):
        if uid is not None and uid not in self.persona_cache:
            raise ValueError(
                f"User ID {uid} not found in persona cache. You need to call 'init' or 'load_profile' first."
            )

        if uid is None:
            persona_tuple = [(uid, cache) for uid, cache in self.persona_cache.items()]
        else:
            persona_tuple = [(uid, self.persona_cache[uid])]

        # save profiler
        for _uid, persona in persona_tuple:
            await self.profiler.save(
                uid=_uid, persona=persona, work_dir=self.session_runtime.avatar_path
            )

    """Profiler Op"""

    async def update_profile_details(self, *, uid: str | None = None):
        if uid is not None and uid not in self.persona_cache:
            raise ValueError(
                f"User ID {uid} not found in persona cache. You need to call 'init' or 'load_profile' first."
            )

        if uid is None:
            persona_tuple = [(uid, cache) for uid, cache in self.persona_cache.items()]
        else:
            persona_tuple = [(uid, self.persona_cache[uid])]

        for _uid, persona in persona_tuple:
            await self.profiler.update(
                uid=_uid, persona=persona, session_runtime=self.session_runtime
            )

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

        return best_uid if best_score >= SPEAKER_MATCH_THRESHOLD else None

    async def update_speaker_vector(self, *, uid: str, speaker_vector: np.ndarray | list[float]):
        if uid not in self.persona_cache:
            logger.error(
                f"User ID {uid} not found in persona cache. You need to call 'init' or 'load_profile' first."
            )
            return

        if self.persona_cache[uid].speaker_vector is None:
            logger.error(
                f"User ID {uid} has no speaker vector in persona cache. You need to call 'insert_speaker' first."
            )
            return

        self.persona_cache[uid].speaker_vector = NumpyOP.l2_normalize(NumpyOP.to_np(speaker_vector))
        debug_every(
            "User ID %s speaker vector updated in persona cache.",
            uid,
            key=f"persona:speaker_vector_updated:{uid}",
            interval_sec=10.0,
        )

    async def update_speaker_attribute(self, *, uid: str, speaker_attribute: dict[str, Any]):
        if uid not in self.persona_cache:
            logger.error(
                f"User ID {uid} not found in persona cache. You need to call 'init' or 'load_profile' first."
            )
            return

        self.persona_cache[uid].update_speaker_profile(speaker_attribute)
        debug_every(
            "User ID %s speaker attribute updated in persona cache.",
            uid,
            key=f"persona:speaker_attribute_updated:{uid}",
            interval_sec=10.0,
        )

    async def insert_speaker_vector(
        self, *, speaker_vector: np.ndarray | list[float]
    ) -> str | None:
        vector = NumpyOP.l2_normalize(NumpyOP.to_np(speaker_vector))
        for cache_uid in self.persona_cache:
            cache = self.persona_cache[cache_uid]

            if cache.profile is None:
                cache.profile = UserProfile(speaker_vector=vector)
                logger.info(f"Speaker vector inserted into persona cache uid={cache_uid}")
                return cache_uid

            if cache.speaker_vector is None:
                cache.speaker_vector = vector
                logger.info(f"Speaker vector attached to default persona cache uid={cache_uid}")
                return cache_uid

        logger.warning("No available user profile can be inserted with speaker vector.")
        return None

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

        return best_uid if best_score >= FACE_MATCH_THRESHOLD else None

    async def update_face_vector(self, *, uid: str, face_vector: np.ndarray | list[float]):
        if uid not in self.persona_cache:
            logger.error(
                f"User ID {uid} not found in persona cache. You need to call 'init' or 'load_profile' first."
            )
            return

        self.persona_cache[uid].face_vector = NumpyOP.l2_normalize(NumpyOP.to_np(face_vector))
        debug_every(
            "User ID %s face vector updated in persona cache.",
            uid,
            key=f"persona:face_vector_updated:{uid}",
            interval_sec=10.0,
        )

    async def update_face_attribute(self, *, uid: str, face_attribute: dict[str, Any]):
        if uid not in self.persona_cache:
            logger.error(
                f"User ID {uid} not found in persona cache. You need to call 'init_cache' first."
            )
            return

        self.persona_cache[uid].update_face_profile(face_attribute)
        debug_every(
            "User ID %s face attribute updated in persona cache.",
            uid,
            key=f"persona:face_attribute_updated:{uid}",
            interval_sec=10.0,
        )

    async def insert_face_vector(self, *, face_vector: np.ndarray | list[float]) -> str | None:
        vector = NumpyOP.l2_normalize(NumpyOP.to_np(face_vector))
        for cache_uid in self.persona_cache:
            cache = self.persona_cache[cache_uid]

            if cache.profile is None:
                cache.profile = UserProfile(face_vector=vector)
                logger.info(f"Face vector inserted into default persona cache uid={cache_uid}")
                return cache_uid

            if cache.face_vector is None:
                cache.face_vector = vector
                logger.info(f"Face vector attached to default persona cache uid={cache_uid}")
                return cache_uid

        logger.warning("No available user profile can be inserted with face vector.")
        return None

    """Runtime Op"""

    async def on_session_start(self, **kwargs) -> None:
        primary_user_id = self.session_runtime.primary_user_id
        if not primary_user_id:
            return

        await self.load_profile(uid=primary_user_id)

    async def on_session_stop(self, **kwargs) -> None:
        await self.update_profile_details()
        await self.save()
