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
import logging
from collections.abc import Sequence

from alphaavatar.agents.constants import FACE_MATCH_THRESHOLD, SPEAKER_MATCH_THRESHOLD
from alphaavatar.agents.persona import PersonaBase, PersonaCache, PersonaProcessorBase
from alphaavatar.agents.persona.schemas import UserProfile, UserRuntimeState
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import AvatarCapabilityRegistry
from alphaavatar.agents.runtime.modules.session.runtime import ParticipantInfo
from alphaavatar.agents.utils import NumpyOP
from alphaavatar.agents.utils.files.work_dirs import prepare_user_path
from alphaavatar.core.cleanup import wait_for_cleanup

from .cache import DefaultPersonaCache
from .storage import PersonaStore
from .template import PersonaPluginsTemplate

logger = logging.getLogger(__name__)


class PersonaRuntime(PersonaBase):
    def __init__(self, *, runtime: AvatarRuntime, store: PersonaStore) -> None:
        self._runtime = runtime
        self._store = store

        self._persona_cache: dict[str, PersonaCache] = {}
        self._processors: tuple[PersonaProcessorBase, ...] = ()
        self._entered_processors: list[PersonaProcessorBase] = []

        self._processors_bound = False
        self._started = False
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

        self._capability_registry = AvatarCapabilityRegistry()

    @property
    def capability_registry(self) -> AvatarCapabilityRegistry:
        return self._capability_registry

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
        return PersonaPluginsTemplate.apply_provider_template(profiles)

    @staticmethod
    def _can_merge_profiles(
        session_profile: UserProfile | None, loaded_profile: UserProfile
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
        loaded_profile: UserProfile, session_profile: UserProfile | None
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

    @staticmethod
    def _observe(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    def _ensure_runtime_state(self, profile: UserProfile) -> UserRuntimeState:
        if profile.runtime_state is None:
            profile.runtime_state = UserRuntimeState()
        return profile.runtime_state

    def _update_runtime_state(self, *, participant: ParticipantInfo, profile: UserProfile) -> None:
        state = self._ensure_runtime_state(profile)
        session_id = self._runtime.session.session_id

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

    def bind_processors(self, processors: Sequence[PersonaProcessorBase]) -> None:
        if self._processors_bound:
            raise RuntimeError("Persona processors have already been bound.")
        if self._start_task is not None or self._close_task is not None:
            raise RuntimeError("Persona processors cannot be bound after runtime start or stop")

        names = [processor.name for processor in processors]
        if len(names) != len(set(names)):
            raise ValueError(f"Persona processor names must be unique: {names}")

        registry = AvatarCapabilityRegistry(*processors)

        self._processors = tuple(processors)
        self._capability_registry = registry
        self._processors_bound = True

    async def load_profile(self, *, uid: str) -> None:
        if uid in self._persona_cache:
            return

        participant = self._runtime.session.get_participant(user_id=uid)
        profile = await self._store.load(uid=uid)

        if participant is None and profile.is_empty:
            logger.warning("No participant or persistent Persona profile uid=%s", uid)
            return

        if participant is not None:
            self._update_runtime_state(participant=participant, profile=profile)
            self._persona_cache[uid] = DefaultPersonaCache(
                participant=participant, user_profile=profile
            )
            return

        for cache_uid in tuple(self._persona_cache):
            cache = self._persona_cache[cache_uid]

            if not self._can_merge_profiles(cache.profile, profile):
                continue

            user_path = self._runtime.workspace.users.get(uid)
            prepare_user_path(user_path)

            self._runtime.session.resolve_participant_user(
                participant_id=cache.participant.participant_id, user_id=uid, user_path=user_path
            )

            self._update_runtime_state(participant=cache.participant, profile=profile)

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

        errors: list[Exception] = []
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                failure = RuntimeError("Persona profile save cancelled itself")
                failure.__cause__ = result
                errors.append(failure)
            elif isinstance(result, Exception):
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result
        if errors:
            raise ExceptionGroup("One or more Persona profiles failed to save", errors)

    async def _start(self) -> None:
        primary_user_id = self._runtime.session.primary_user_id
        if primary_user_id:
            await self.load_profile(uid=primary_user_id)

        for processor in self._processors:
            # A failing start may already own subscriptions or provider resources.
            self._entered_processors.append(processor)
            await processor.start()

        task = asyncio.current_task()
        if self._close_task is not None or (task is not None and task.cancelling()):
            raise asyncio.CancelledError

        self._started = True
        logger.info("Persona started processors=%s", [p.name for p in self._processors])

    async def _close(self) -> None:
        start = self._start_task
        if start is not None:
            if not start.done() and not start.cancelling():
                start.cancel()
            await asyncio.gather(start, return_exceptions=True)

        finalize = self._started
        self._started = False
        errors: list[Exception] = []

        async def close_step(operation) -> None:
            try:
                await operation
            except asyncio.CancelledError as error:
                failure = RuntimeError("Persona cleanup operation cancelled itself")
                failure.__cause__ = error
                errors.append(failure)
            except Exception as error:
                errors.append(error)

        for processor in reversed(self._entered_processors):
            await close_step(processor.stop(finalize=finalize))
        self._entered_processors.clear()

        # Rollback must not finalize or persist an incompletely started session.
        if finalize:
            await close_step(self.save())
        if errors:
            raise ExceptionGroup("Persona shutdown failed", errors)

        logger.info("Persona stopped")

    async def on_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Persona runtime is closing or closed")
        if not self._processors_bound:
            raise RuntimeError("Persona processors have not been bound")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="persona_runtime_start")
            self._start_task.add_done_callback(self._observe)
        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None:
                raise RuntimeError("Persona closed during startup")
        except BaseException as original:
            try:
                await self.on_stop()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def on_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="persona_runtime_close")
            self._close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._close_task)
