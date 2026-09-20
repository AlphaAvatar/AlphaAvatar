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
from datetime import datetime
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from alphaavatar.agents.persona import (
    PersonaBase,
    PersonaCache,
    PersonaProcessorBase,
)
from alphaavatar.agents.providers import ProviderGateway, ProvidersConfig
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import (
    AvatarCapabilityName,
    avatar_capability,
)
from alphaavatar.agents.utils.time import application_now
from alphaavatar.core.turn import TurnInputModality, TurnSnapshot

from ...log import logger
from ...profile import UserProfileDetails
from ...template import PersonaPluginsTemplate
from .op import (
    ProfileDelta,
    append_string,
    append_text,
    clear_path,
    parse_pointer,
    remove_string,
    write_set,
)

DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a "profile delta extractor". Compare the NEW TURN to the CURRENT PROFILE and output only CHANGES as PatchOps.

Constraints (FLAT schema, no nested objects):
- Paths MUST be single-segment, top-level keys ONLY (e.g., "/name", "/gender", "/preferences", "/constraints").
  Do NOT use nested paths like "/preferences/interests" or "/location/country" — nested structures are NOT allowed.

List fields (list of strings):
  - Use op=append to add ONE string item (avoid duplicates)
  - Use op=remove to remove ONE string item
  - Use op=set ONLY if replacing the entire list (value must be a list of strings)

String fields:
  - Use op=set to overwrite the whole string
  - Use op=append to CONCATENATE text to the end (like "+="). Keep it short and natural.
  - Use op=clear to empty the string (set to "")

General:
- evidence must quote the original sentence or a tight paraphrase; set confidence in [0,1].
- If nothing changes, return an empty list.
- Avoid hallucinations. Do not invent values not clearly stated or strongly implied.
""",
        ),
        (
            "human",
            "CURRENT PROFILE (JSON):\n```{current_profile}```\n\n"
            "REFERENCE PROFILE FIELDS (type + description):\n```{profile_reference}```\n\n"
            "NEW TURN:\n```{new_turn}```\n\n"
            "Output only ProfileDelta (list of PatchOps, If nothing changes, return an empty list).",
        ),
    ]
)


class ProfilerRuntimeConfig(BaseModel):
    profile_delta_task: str = "persona.profile_delta"
    gateway: ProvidersConfig = Field(default_factory=ProvidersConfig)


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
        self,
        *,
        runtime: AvatarRuntime,
        persona: PersonaBase,
        provider: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(runtime=runtime, persona=persona)

        config = ProfilerRuntimeConfig(**provider) if provider else ProfilerRuntimeConfig()
        self._profile_delta_task = config.profile_delta_task
        self._provider_gateway = ProviderGateway(config.gateway)
        self._provider_gateway.validate_tasks([self._profile_delta_task])

        self._consumer_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "profiler"

    async def _aextract_delta(
        self,
        *,
        uid: str,
        profile_details_dump: dict,
        new_turn: str,
    ) -> ProfileDelta:
        result = await self._provider_gateway.ainvoke_structured(
            task_name=self._profile_delta_task,
            prompt=DELTA_PROMPT,
            payload={
                "current_profile": profile_details_dump,
                "profile_reference": UserProfileDetails.field_descriptions_prompt(),
                "new_turn": new_turn,
            },
            output_schema=ProfileDelta,
            metadata={
                "provider_dir": self.session_runtime.session_path.provider_dir,
                "plugin": "persona",
                "component": "profiler",
                "operation": "profile_delta",
                "user_id": uid,
                "session_id": self.session_runtime.session_id,
            },
        )
        return result.output

    def _apply_delta(
        self,
        updated_at: datetime,
        profile_details_dump: dict,
        delta: ProfileDelta,
    ) -> tuple[bool, dict[str, Any]]:
        data = deepcopy(profile_details_dump)
        updated = False

        for patch in delta.ops:
            tokens = parse_pointer(patch.path)
            if not tokens or len(tokens) != 1:
                continue

            try:
                if patch.op == "set":
                    write_set(data, tokens, patch.value, updated_at)
                elif patch.op == "clear":
                    clear_path(data, tokens)
                elif patch.op == "append" and patch.value is not None:
                    current = data.get(tokens[0])
                    if isinstance(current, list):
                        append_string(data, tokens, patch.value, updated_at)
                    else:
                        append_text(data, tokens, patch.value, updated_at)
                elif patch.op == "remove" and patch.value is not None:
                    remove_string(data, tokens, patch.value)
                updated = True
            except Exception:
                logger.exception(
                    "Failed to apply profile delta uid operation=%s path=%s",
                    patch.op,
                    patch.path,
                )

        return updated, data

    async def _update_profile(self, uid: str, persona_cache: PersonaCache) -> None:
        if not persona_cache.turns:
            return

        current = (
            persona_cache.profile_details.model_dump()
            if persona_cache.profile_details is not None
            else {}
        )

        delta = await self._aextract_delta(
            uid=uid,
            profile_details_dump=persona_cache.profile_details_dump_value,
            new_turn=PersonaPluginsTemplate.apply_update_template(persona_cache.turns),
        )

        is_updated, details = self._apply_delta(application_now(), current, delta)
        if is_updated:
            logger.info(f"[uid: {uid}] User Profile UPDATE success: {details}")
            persona_cache.profile_details = UserProfileDetails(**details)
        else:
            logger.info(f"[uid: {uid}] User Profile output is empty, UPDATE skip!")

    """Processor Loop"""

    def _target_uids(self, snapshot: TurnSnapshot) -> tuple[str, ...]:
        uids = []

        for actor in snapshot.actors:
            uid = actor.user_id or (
                actor.entity.resolved_entity_id if actor.entity is not None else None
            )
            if uid and uid not in uids:
                uids.append(uid)

        if uids:
            return tuple(uids)

        if len(self.session_runtime.participants) == 1 and self.session_runtime.primary_user_id:
            return (self.session_runtime.primary_user_id,)

        return ()

    async def _record_turn(self, snapshot: TurnSnapshot) -> None:
        if snapshot.modality == TurnInputModality.SYSTEM or not (snapshot.text or "").strip():
            return

        for uid in self._target_uids(snapshot):
            if uid not in self.persona.persona_cache:
                await self.persona.load_profile(uid=uid)

            cache = self.persona.persona_cache.get(uid)
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
                        "Persona profiler missed committed turns missed=%s",
                        batch.missed_count,
                    )

                for event in batch.items:
                    await self._record_turn(event.snapshot)

                stream.commit(
                    consumer_id=self.CONSUMER_ID,
                    cursor_seq=batch.cursor_seq,
                )

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
                    "Persona profiler missed committed turns missed=%s",
                    batch.missed_count,
                )

            for event in batch.items:
                await self._record_turn(event.snapshot)

            if batch.cursor_seq > batch.committed_cursor_seq:
                stream.commit(
                    consumer_id=self.CONSUMER_ID,
                    cursor_seq=batch.cursor_seq,
                )

            if not batch.items or batch.remaining_count == 0:
                return

    """Runtime operations"""

    async def _start(self) -> None:
        self._consumer_task = asyncio.create_task(
            self._consume_turns(),
            name="persona_profiler_turn_consumer",
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
                self._update_profile(uid, cache)
                for uid, cache in self.persona.persona_cache.items()
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
            raise ExceptionGroup(
                "One or more Persona profiles failed to update",
                errors,
            )

        logger.info("Persona Profiler stopped")
