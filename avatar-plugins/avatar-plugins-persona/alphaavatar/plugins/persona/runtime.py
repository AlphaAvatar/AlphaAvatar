# Copyright 2026 AlphaAvatar project
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

import asyncio
from collections.abc import Sequence

from livekit.agents.llm import ChatItem

from alphaavatar.agents.constants import FACE_MATCH_THRESHOLD, SPEAKER_MATCH_THRESHOLD
from alphaavatar.agents.log import logger
from alphaavatar.agents.persona import (
    PersonaBase,
    PersonaCache,
    PersonaPluginsTemplate,
    PersonaProcessorBase,
)
from alphaavatar.agents.persona.schemas import UserProfile, UserRuntimeState
from alphaavatar.agents.runtime import AvatarRuntime, SessionRuntime
from alphaavatar.agents.runtime.capability import AvatarCapability
from alphaavatar.agents.runtime.session_runtime import ParticipantInfo
from alphaavatar.agents.utils import NumpyOP
from alphaavatar.agents.utils.files.work_dirs import prepare_user_path

from .cache import DefaultPersonaCache
from .storage import PersonaStore


class PersonaRuntime(PersonaBase):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        store: PersonaStore,
    ) -> None:
        self._runtime = runtime
        self._store = store

        self._persona_cache: dict[str, PersonaCache] = {}
        self._processors: tuple[PersonaProcessorBase, ...] = ()
        self._started_processors: list[PersonaProcessorBase] = []

        self._processors_bound = False
        self._profiler_enabled = False
        self._started = False
        self._capabilities: tuple[AvatarCapability, ...] = ()

    @property
    def capabilities(self) -> tuple[AvatarCapability, ...]:
        return self._capabilities

    @property
    def processors(self) -> tuple[PersonaProcessorBase, ...]:
        return self._processors

    @property
    def session_runtime(self) -> SessionRuntime:
        return self._runtime.session

    @property
    def persona_cache(self) -> dict[str, PersonaCache]:
        return self._persona_cache

    @property
    def store(self) -> PersonaStore:
        return self._store

    @property
    def persona_content(self) -> str:
        profiles = {
            uid: cache.profile
            for uid, cache in self._persona_cache.items()
            if cache.profile is not None
        }
        return PersonaPluginsTemplate.apply_system_template(profiles)

    @staticmethod
    def _can_merge_profiles(
        session_profile: UserProfile | None,
        loaded_profile: UserProfile,
    ) -> bool:
        if session_profile is None:
            return True

        if session_profile.speaker_vector is not None and loaded_profile.speaker_vector is not None:
            score = float(
                NumpyOP.l2_normalize(NumpyOP.to_np(session_profile.speaker_vector))
                @ NumpyOP.l2_normalize(NumpyOP.to_np(loaded_profile.speaker_vector))
            )
            if score < SPEAKER_MATCH_THRESHOLD:
                return False

        if session_profile.face_vector is not None and loaded_profile.face_vector is not None:
            score = float(
                NumpyOP.l2_normalize(NumpyOP.to_np(session_profile.face_vector))
                @ NumpyOP.l2_normalize(NumpyOP.to_np(loaded_profile.face_vector))
            )
            if score < FACE_MATCH_THRESHOLD:
                return False

        return True

    @staticmethod
    def _merge_profiles(
        loaded_profile: UserProfile,
        session_profile: UserProfile | None,
    ) -> UserProfile:
        if session_profile is None:
            return loaded_profile

        if loaded_profile.details is None:
            loaded_profile.details = session_profile.details
        if loaded_profile.speaker_vector is None:
            loaded_profile.speaker_vector = session_profile.speaker_vector
        if loaded_profile.face_vector is None:
            loaded_profile.face_vector = session_profile.face_vector

        return loaded_profile

    def _ensure_runtime_state(self, profile: UserProfile) -> UserRuntimeState:
        if profile.runtime_state is None:
            profile.runtime_state = UserRuntimeState()
        return profile.runtime_state

    def _update_runtime_state(
        self,
        *,
        participant: ParticipantInfo,
        profile: UserProfile,
    ) -> None:
        state = self._ensure_runtime_state(profile)
        session_id = self.session_runtime.session_id

        if state.current_session_id == session_id:
            state.current_timezone = participant.user_time.timezone
            state.current_login_at = participant.joined_at
            state.current_room_type = participant.room_type
            return

        if state.current_session_id:
            state.last_timezone = state.current_timezone
            state.last_login_at = state.current_login_at
            state.last_session_id = state.current_session_id
            state.last_room_type = state.current_room_type

        state.current_timezone = participant.user_time.timezone
        state.current_login_at = participant.joined_at
        state.current_session_id = session_id
        state.current_room_type = participant.room_type
        state.login_count += 1

    def add_message(self, *, chat_item: ChatItem) -> None:
        if not self._profiler_enabled:
            return

        for cache in self._persona_cache.values():
            cache.add_message(chat_item)

    def bind_processors(self, processors: Sequence[PersonaProcessorBase]) -> None:
        if self._processors_bound:
            raise RuntimeError("Persona processors have already been bound.")
        if self._started:
            raise RuntimeError("Persona processors cannot be bound after runtime start.")

        names = [processor.name for processor in processors]
        if len(names) != len(set(names)):
            raise ValueError(f"Persona processor names must be unique: {names}")

        self._processors = tuple(processors)
        self._processors_bound = True
        self._profiler_enabled = "profiler" in names

        capabilities: dict[object, AvatarCapability] = {}
        for processor in processors:
            for capability in processor.capabilities:
                capabilities.setdefault(capability.name, capability)

        self._capabilities = tuple(capabilities.values())

    async def load_profile(self, *, uid: str) -> None:
        if uid in self._persona_cache:
            return

        participant = self.session_runtime.get_participant(user_id=uid)
        profile = await self._store.load(uid=uid)

        if participant is None and profile.is_empty:
            logger.warning("No participant or persistent Persona profile uid=%s", uid)
            return

        if participant is not None:
            self._update_runtime_state(participant=participant, profile=profile)
            self._persona_cache[uid] = DefaultPersonaCache(
                participant=participant,
                user_profile=profile,
            )
            return

        for cache_uid in tuple(self._persona_cache):
            cache = self._persona_cache[cache_uid]

            if not self._can_merge_profiles(cache.profile, profile):
                continue

            user_path = self._runtime.workspace.users.get(uid)
            prepare_user_path(user_path)

            self.session_runtime.resolve_participant_user(
                participant_id=cache.participant.participant_id,
                user_id=uid,
                user_path=user_path,
            )

            self._update_runtime_state(
                participant=cache.participant,
                profile=profile,
            )

            cache.profile = self._merge_profiles(profile, cache.profile)

            del self._persona_cache[cache_uid]
            self._persona_cache[uid] = cache
            return

        logger.warning("Persistent Persona profile could not be attached uid=%s", uid)

    async def save(self, *, uid: str | None = None) -> None:
        if uid is not None:
            cache = self._persona_cache.get(uid)
            if cache is None:
                raise ValueError(f"Unknown Persona uid={uid!r}")
            targets = ((uid, cache),)
        else:
            targets = tuple(self._persona_cache.items())

        results = await asyncio.gather(
            *(self._store.save(uid=target_uid, persona=cache) for target_uid, cache in targets),
            return_exceptions=True,
        )

        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise ExceptionGroup("One or more Persona profiles failed to save", errors)

    async def on_session_start(self) -> None:
        if self._started:
            return
        if not self._processors_bound:
            raise RuntimeError("Persona processors have not been bound.")

        primary_user_id = self.session_runtime.primary_user_id
        if primary_user_id:
            await self.load_profile(uid=primary_user_id)

        try:
            for processor in self._processors:
                await processor.start()
                self._started_processors.append(processor)
        except BaseException:
            for processor in reversed(self._started_processors):
                try:
                    await processor.stop(finalize=False)
                except Exception:
                    logger.exception(
                        "Failed to rollback Persona processor name=%s",
                        processor.name,
                    )

            self._started_processors.clear()
            raise

        self._started = True

        logger.info(
            "Persona started processors=%s",
            [processor.name for processor in self._processors],
        )

    async def on_session_stop(self) -> None:
        if not self._started and not self._started_processors:
            return

        errors: list[Exception] = []

        for processor in reversed(self._started_processors):
            try:
                await processor.stop()
            except Exception as exc:
                errors.append(exc)

        self._started_processors.clear()
        self._started = False

        try:
            await self.save()
        except Exception as exc:
            errors.append(exc)

        if errors:
            raise ExceptionGroup("Persona shutdown failed", errors)

        logger.info("Persona stopped")
