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
from datetime import UTC, datetime

from alphaavatar.agents.persona import PersonaBase, PersonaCache, PersonaProcessorBase
from alphaavatar.agents.persona.schemas import UserRuntimeState
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import AvatarCapabilityRegistry
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.session.schemas import Participant
from alphaavatar.core.turn.schemas import TurnSnapshot

from .cache import DefaultPersonaCache
from .storage import PersonaStore
from .template import PersonaPluginsTemplate

logger = logging.getLogger(__name__)


class PersonaRuntime(PersonaBase):
    CONSUMER_ID = "persona.session"

    def __init__(self, *, runtime: AvatarRuntime, store: PersonaStore) -> None:
        self._runtime = runtime
        self._store = store

        self._persona_cache: dict[str, DefaultPersonaCache] = {}
        self._processors: tuple[PersonaProcessorBase, ...] = ()
        self._entered_processors: list[PersonaProcessorBase] = []

        self._processors_bound = False
        self._started = False
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._session_task: asyncio.Task[None] | None = None
        self._load_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_loads: set[asyncio.Task[None]] = set()
        self._save_lock = asyncio.Lock()

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
        """Unscoped context contains observations only, never loaded user profiles."""
        profiles = {}
        for participant in self._runtime.session.participants.values():
            cache = self.cache_for(participant.participant_id)
            if cache is None:
                continue

            profile = cache.observation_profile
            profile.runtime_state = None
            if not profile.is_empty:
                label = (
                    f"{participant.user_id or 'unknown'} (participant {participant.participant_id})"
                )
                profiles[label] = profile

        return PersonaPluginsTemplate.apply_provider_template(profiles)

    @staticmethod
    def _observe(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    def _runtime_state(
        self, participant: Participant, previous: UserRuntimeState | None
    ) -> UserRuntimeState:
        state = previous.model_copy(deep=True) if previous is not None else UserRuntimeState()
        session_id = self._runtime.session.session_id
        login_at = datetime.fromtimestamp(participant.joined_at.unix_seconds, UTC)
        if state.current_session_id != session_id:
            state.last_timezone = state.current_timezone
            state.last_login_at = state.current_login_at
            state.last_session_id = state.current_session_id
            state.last_room_type = state.current_room_type
            state.login_count += 1
        elif state.current_login_at is not None:
            login_at = min(login_at, state.current_login_at)

        state.current_timezone = participant.timezone
        state.current_login_at = login_at
        state.current_session_id = session_id
        state.current_room_type = self._runtime.state.interaction_method.room_type
        return state

    def cache_for(self, participant_id: str) -> DefaultPersonaCache | None:
        participant = self._runtime.participants.get(participant_id)
        if participant is None:
            return None

        cache = self._persona_cache.get(participant_id)
        if cache is None:
            cache = self._persona_cache[participant_id] = DefaultPersonaCache(
                participant=participant
            )
        else:
            cache.participant = participant

        if participant.user_id is None or not self._runtime.participants.accepts_identity(
            participant
        ):
            cache.clear_base()

        cache.runtime_state = self._runtime_state(participant, cache.runtime_state)
        return cache

    def content_for(self, snapshot: TurnSnapshot) -> str:
        if self._runtime.turn.get(snapshot.input_id) is not snapshot:
            raise ValueError("Persona context requires a Turn owned by this runtime")

        profiles = {}
        for actor in self._runtime.participants.project_turn(snapshot).actors:
            if actor.participant_id is None:
                continue

            participant = self._runtime.participants.get(actor.participant_id)
            if (
                participant is None
                or actor.user_id != participant.user_id
                or actor.identity_sequence != participant.identity_sequence
                or not self._runtime.participants.accepts_identity(participant)
            ):
                continue

            cache = self.cache_for(participant.participant_id)
            if cache is not None and (profile := cache.profile) is not None:
                label = (
                    f"{participant.user_id or 'unknown'} (participant {participant.participant_id})"
                )
                profiles[label] = profile

        return PersonaPluginsTemplate.apply_provider_template(profiles)

    def bind_processors(self, processors: Sequence[PersonaProcessorBase]) -> None:
        if self._processors_bound:
            raise RuntimeError("Persona processors have already been bound")
        if self._start_task is not None or self._close_task is not None:
            raise RuntimeError("Persona processors cannot be bound after runtime start or stop")

        names = [processor.name for processor in processors]
        if len(names) != len(set(names)):
            raise ValueError(f"Persona processor names must be unique: {names}")

        self._processors = tuple(processors)
        self._capability_registry = AvatarCapabilityRegistry(*processors)
        self._processors_bound = True

    async def load_profile(self, *, participant_id: str) -> None:
        cache = self.cache_for(participant_id)
        if cache is None:
            raise KeyError(f"Unknown participant: {participant_id}")

        participant = cache.participant
        user_id = participant.user_id
        if user_id is None or not self._runtime.participants.accepts_identity(participant):
            return

        # Current state is already available; local login history does not depend on the VDB.
        previous = await self._store.load_runtime_state(participant=participant)
        if not self._runtime.participants.accepts_identity(participant):
            return

        cache.runtime_state = self._runtime_state(participant, previous)
        profile = await self._store.load(participant=participant)
        if not self._runtime.participants.accepts_identity(participant):
            return

        cache.set_base(profile)

    async def save(self, *, user_id: str | None = None) -> None:
        async with self._save_lock:
            targets = []
            for participant in self._runtime.session.snapshot().participants.values():
                target_user_id = participant.user_id
                if target_user_id is None:
                    continue

                if user_id is not None and target_user_id != user_id:
                    continue

                if not self._runtime.participants.accepts_identity(participant):
                    continue

                cache = self.cache_for(participant.participant_id)
                if cache is None:
                    continue

                if cache.participant.identity_sequence != participant.identity_sequence:
                    continue

                targets.append(cache.snapshot())

            if user_id is not None and not targets:
                raise PermissionError(f"No writable Persona participant for user_id={user_id!r}")

            # Each write owns a pinned identity and observation copy, independent of later rebinding.
            results = await asyncio.gather(
                *(self._store.save(persona=cache) for cache in targets), return_exceptions=True
            )
            errors = []
            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, Exception):
                    errors.append(result)
                elif isinstance(result, BaseException):
                    raise result

            if errors:
                raise ExceptionGroup("One or more Persona profiles failed to save", errors)

    """Session Loop"""

    def _schedule_load(self, participant: Participant) -> None:
        participant_id = participant.participant_id
        previous = self._load_tasks.get(participant_id)
        if previous is not None and not previous.done():
            previous.cancel()

        cache = self.cache_for(participant_id)
        if (
            cache is None
            or participant.user_id is None
            or not self._runtime.participants.accepts_identity(participant)
        ):
            return

        task = asyncio.create_task(
            self.load_profile(participant_id=participant_id),
            name=f"persona_profile:{participant_id}",
        )
        self._load_tasks[participant_id] = task
        self._pending_loads.add(task)

        def complete(finished: asyncio.Task[None]) -> None:
            self._pending_loads.discard(finished)
            if self._load_tasks.get(participant_id) is finished:
                self._load_tasks.pop(participant_id, None)
            if not finished.cancelled() and (error := finished.exception()) is not None:
                logger.warning(
                    "Persona profile load failed participant=%s: %s", participant_id, error
                )

        task.add_done_callback(complete)

    def _sync_session(self) -> None:
        stream = self._runtime.session.events
        batch = stream.read_pending(consumer_id=self.CONSUMER_ID)
        if batch.has_gap:
            # This consumer owns only read-only views; persisted writes use their own snapshots.
            snapshot = self._runtime.session.snapshot()
            for participant in snapshot.participants.values():
                self._schedule_load(participant)

            stream.commit(consumer_id=self.CONSUMER_ID, cursor_seq=snapshot.sequence)
            return

        for event in batch.items:
            if event.participant is not None:
                current = self._runtime.participants.get(event.participant.participant_id)
                if current is not None:
                    self._schedule_load(current)

        stream.commit(consumer_id=self.CONSUMER_ID, cursor_seq=batch.cursor_seq)

    async def _consume_session(self) -> None:
        stream = self._runtime.session.events
        while await stream.wait_for_pending(consumer_id=self.CONSUMER_ID):
            self._sync_session()

    """Runtime operations"""

    async def _start(self) -> None:
        self._sync_session()
        self._session_task = asyncio.create_task(self._consume_session(), name=self.CONSUMER_ID)

        for processor in self._processors:
            self._entered_processors.append(processor)
            await processor.start()

        task = asyncio.current_task()
        if self._close_task is not None or (task is not None and task.cancelling()):
            raise asyncio.CancelledError

        self._started = True
        logger.info(
            "Persona started processors=%s", [processor.name for processor in self._processors]
        )

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
        if self._session_task is not None:
            self._session_task.cancel()
            await asyncio.gather(self._session_task, return_exceptions=True)
            self._session_task = None

        tasks = tuple(self._pending_loads)
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        self._load_tasks.clear()
        self._pending_loads.clear()
        self._runtime.session.events.clear_consumer(self.CONSUMER_ID)

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
