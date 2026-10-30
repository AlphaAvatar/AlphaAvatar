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
import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, get_args, get_origin

from alphaavatar.agents.persona import PersonaBase, PersonaCache, PersonaProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import avatar_capability
from alphaavatar.agents.runtime.capability.enums import AvatarCapabilityName
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnSnapshot

from ...log import logger
from ...profile import UserProfileDetails
from ...template import PersonaPluginsTemplate
from .config import ProfilerConfig
from .op import (
    ProfileDelta,
    append_string,
    append_text,
    clear_path,
    parse_pointer,
    remove_string,
    write_set,
)
from .provider import ProfilerProvider


@avatar_capability(
    name=AvatarCapabilityName.PERSONA_PROFILE,
    description=(
        "Can maintain persistent user profiles from conversations and observed traits, "
        "and use them to personalize interactions across sessions."
    ),
)
class ProfilerProcessor(PersonaProcessorBase):
    CONSUMER_ID = "persona.profiler.turn"

    def __init__(
        self, *, runtime: AvatarRuntime, persona: PersonaBase, config: ProfilerConfig
    ) -> None:
        super().__init__(runtime=runtime, persona=persona)

        self._config = config
        self._provider = ProfilerProvider(config.provider, service=runtime.foundation.provider)
        self._consumer_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "profiler"

    @staticmethod
    def _is_list_field(name: str) -> bool:
        annotation = UserProfileDetails.model_fields[name].annotation
        return get_origin(annotation) is list or any(
            get_origin(value) is list for value in get_args(annotation)
        )

    async def _aextract_delta(
        self, *, user_id: str, profile_details_dump: dict[str, Any], new_turn: str
    ) -> ProfileDelta:
        return await self._provider.extract(
            profile_details_dump=profile_details_dump,
            new_turn=new_turn,
            metadata={
                "provider_dir": self.runtime.session_path.provider_dir,
                "plugin": "persona",
                "component": "profiler",
                "operation": "profile_delta",
                "user_id": user_id,
                "session_id": self.session_runtime.session_id,
            },
        )

    def _apply_delta(
        self, updated_at: datetime, profile_details_dump: dict, delta: ProfileDelta
    ) -> tuple[bool, dict[str, Any]]:
        data = deepcopy(profile_details_dump)
        updated = False

        for patch in delta.ops:
            tokens = parse_pointer(patch.path)
            if len(tokens) != 1 or tokens[0] not in UserProfileDetails.model_fields:
                continue

            try:
                if patch.op == "set":
                    write_set(data, tokens, patch.value, updated_at)
                elif patch.op == "clear":
                    clear_path(data, tokens)
                elif patch.op == "append" and patch.value is not None:
                    current = data.get(tokens[0])
                    if isinstance(current, list) or self._is_list_field(tokens[0]):
                        append_string(data, tokens, patch.value, updated_at)
                    else:
                        append_text(data, tokens, patch.value, updated_at)
                elif patch.op == "remove" and patch.value is not None:
                    remove_string(data, tokens, patch.value)
                updated = True
            except Exception:
                logger.exception(
                    "Failed to apply profile delta user_id operation=%s path=%s",
                    patch.op,
                    patch.path,
                )

        return updated, data

    async def _update_profile(self, participant_id: str, persona_cache: PersonaCache) -> None:
        if not persona_cache.turns:
            return

        participant = self.session_runtime.get_participant(participant_id=participant_id)
        if participant is None or participant.user_id is None:
            return

        current = (
            persona_cache.profile_details.model_dump()
            if persona_cache.profile_details is not None
            else {}
        )

        delta = await self._aextract_delta(
            user_id=participant.user_id,
            profile_details_dump=persona_cache.profile_details_dump_value,
            new_turn=PersonaPluginsTemplate.apply_update_template(persona_cache.turns),
        )

        latest = self.session_runtime.get_participant(participant_id=participant_id)
        if latest is None or latest.identity_sequence != participant.identity_sequence:
            return

        updated_at = datetime.fromtimestamp(self.runtime.clock.now().unix_seconds, UTC)
        is_updated, details = self._apply_delta(updated_at, current, delta)
        if is_updated:
            persona_cache.profile_details = UserProfileDetails(**details)
            operations = {}
            for patch in delta.ops:
                tokens = parse_pointer(patch.path)
                if len(tokens) == 1 and tokens[0] in UserProfileDetails.model_fields:
                    operations.setdefault(tokens[0], []).append(
                        {
                            "op": patch.op,
                            "value": patch.value,
                            "list": self._is_list_field(tokens[0]),
                        }
                    )

            persona_cache.mark_profile_fields(set(operations), updated_at=updated_at)
            persona_cache.record_profile_operations(operations)
            logger.info("Persona profile observations updated participant=%s", participant_id)

    """Processor Loop"""

    async def _record_turn(self, snapshot: TurnSnapshot) -> None:
        if snapshot.modality == TurnInputModality.SYSTEM or not (snapshot.text or "").strip():
            return

        # A claimed user_id is not a physical speaker; only explicit participant references count.
        for participant_id in dict.fromkeys(actor.participant_id for actor in snapshot.actors):
            if participant_id is None:
                continue

            participant = self.session_runtime.get_participant(participant_id=participant_id)
            if participant is None:
                continue

            cache = self.persona.cache_for(participant_id)
            if cache is not None:
                cache.add_turn(snapshot)

    async def _consume_turns(self) -> None:
        stream = self.runtime.turn.events

        while True:
            try:
                await stream.wait_for_pending(consumer_id=self.CONSUMER_ID)
                batch = stream.read_pending(consumer_id=self.CONSUMER_ID, limit=8)

                if batch.has_gap:
                    logger.warning(
                        "Persona profiler missed committed turns missed=%s", batch.missed_count
                    )

                for event in batch.items:
                    await self._record_turn(event.snapshot)

                stream.commit(consumer_id=self.CONSUMER_ID, cursor_seq=batch.cursor_seq)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Persona profiler turn consumer failed")
                await asyncio.sleep(0.05)

    async def _drain_turns(self) -> None:
        stream = self.runtime.turn.events

        while True:
            batch = stream.read_pending(consumer_id=self.CONSUMER_ID, limit=32)

            if batch.has_gap:
                logger.warning(
                    "Persona profiler missed committed turns missed=%s", batch.missed_count
                )

            for event in batch.items:
                await self._record_turn(event.snapshot)

            if batch.cursor_seq > batch.committed_cursor_seq:
                stream.commit(consumer_id=self.CONSUMER_ID, cursor_seq=batch.cursor_seq)

            if not batch.items or batch.remaining_count == 0:
                return

    """Runtime operations"""

    async def _start(self) -> None:
        self._consumer_task = asyncio.create_task(
            self._consume_turns(), name="persona_profiler_turn_consumer"
        )
        logger.info("Persona Profiler started")

    async def _stop(self, *, finalize: bool) -> None:
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            await asyncio.gather(self._consumer_task, return_exceptions=True)
            self._consumer_task = None

        if finalize:
            await self._drain_turns()

        self.runtime.turn.events.clear_consumer(self.CONSUMER_ID)

        if not finalize:
            logger.info("Persona Profiler stopped without finalization")
            return

        results = await asyncio.gather(
            *(
                self._update_profile(participant_id, cache)
                for participant_id, cache in self.persona.persona_cache.items()
            ),
            return_exceptions=True,
        )

        errors: list[Exception] = []

        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result

        if errors:
            raise ExceptionGroup("One or more Persona profiles failed to update", errors)

        logger.info("Persona Profiler stopped")
