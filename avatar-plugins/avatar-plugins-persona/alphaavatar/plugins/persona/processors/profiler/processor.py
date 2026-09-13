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
    PersonaPluginsTemplate,
    ProfilerProcessorBase,
)
from alphaavatar.agents.providers import ProviderGateway, ProvidersConfig
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.utils.time import application_now

from ...log import logger
from ...profile import UserProfileDetails
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


class ProfilerProcessor(ProfilerProcessorBase):
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
        if not persona_cache.messages:
            return

        current = (
            persona_cache.profile_details.model_dump()
            if persona_cache.profile_details is not None
            else {}
        )

        delta = await self._aextract_delta(
            uid=uid,
            profile_details_dump=persona_cache.profile_details_dump_value,
            new_turn=PersonaPluginsTemplate.apply_update_template(persona_cache.messages),
        )

        is_updated, details = self._apply_delta(application_now(), current, delta)
        if is_updated:
            logger.info(f"[uid: {uid}] User Profile UPDATE success: {details}")
            persona_cache.profile_details = UserProfileDetails(**details)
        else:
            logger.info(f"[uid: {uid}] User Profile output is empty, UPDATE skip!")

    async def _start(self) -> None:
        logger.info("Persona Profiler started")

    async def _stop(self, *, finalize: bool) -> None:
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
