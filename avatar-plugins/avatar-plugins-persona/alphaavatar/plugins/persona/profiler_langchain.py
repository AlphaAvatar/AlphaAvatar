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
from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from livekit.agents.job import get_job_context

from alphaavatar.agents.avatar import PersonaPluginsTemplate
from alphaavatar.agents.persona import PersonaCache, ProfilerBase, UserProfile, VectorRunnerOP
from alphaavatar.agents.utils.files.work_dirs import UserPath

from .log import logger
from .profiler_details import UserProfileDetails
from .profiler_op import (
    ProfileDelta,
    append_string,
    append_text,
    clear_path,
    flatten_items,
    parse_pointer,
    rebuild_from_items,
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


class ProfilerLangChain(ProfilerBase):
    def __init__(
        self,
        *,
        user_path: UserPath,
        openai_model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        **kwargs,
    ) -> None:
        super().__init__(user_path=user_path)

        llm = ChatOpenAI(model=openai_model, temperature=temperature)  # type: ignore
        self._delta_llm = llm.with_structured_output(ProfileDelta)
        self._chain = DELTA_PROMPT | self._delta_llm

        self._executor = get_job_context().inference_executor

    @property
    def inference_method(self) -> str:
        method = os.getenv("PERSONA_INFERENCE_METHOD")
        if not method:
            raise RuntimeError(
                "PERSONA_INFERENCE_METHOD is not configured. "
                "Make sure AvatarPlugin.bootstrap_inference_runners() is called before "
                "ProfilerLangChain is used."
            )
        return method

    async def _aextract_delta(self, profile_details_dump: dict, new_turn: str) -> ProfileDelta:
        """Ask the LLM to generate patch ops relative to the current profile."""

        return await self._chain.ainvoke(
            {
                "current_profile": profile_details_dump,
                "profile_reference": UserProfileDetails.field_descriptions_prompt(),
                "new_turn": new_turn,
            }
        )

    def _apply_delta(
        self, update_time: str, profile_details_dump: dict, delta: ProfileDelta
    ) -> tuple[bool, dict[str, Any]]:
        """
        Apply PatchOps to a (FLAT) UserProfileDetails:
          - set: overwrite value (scalar/list) at path
          - append/remove:
              * list[str]: append/remove item
              * str: append concatenated text (+=)
          - clear:
              * list -> []
              * str  -> ""
              * others -> None
        """
        data: dict[str, Any] = deepcopy(profile_details_dump)

        is_updated = False
        for op in delta.ops:
            tokens = parse_pointer(op.path)
            if not tokens or len(tokens) != 1:
                continue
            try:
                if op.op == "set":
                    write_set(data, tokens, op.value, update_time)
                elif op.op == "clear":
                    clear_path(data, tokens)
                elif op.op == "append" and op.value is not None:
                    key = tokens[0]
                    cur = data.get(key, None)
                    if isinstance(cur, list):
                        append_string(data, tokens, op.value, update_time)
                    else:
                        append_text(data, tokens, op.value, update_time)
                elif op.op == "remove" and op.value is not None:
                    remove_string(data, tokens, op.value)

                is_updated = True
            except Exception:
                # In production: log the error with op details
                continue

        return is_updated, data

    async def load(
        self,
        *,
        uid: str,
        timeout: float = 3,
    ) -> UserProfile:
        """Load text, voice, and face profile information for the specified user_id"""
        json_data = {"op": VectorRunnerOP.load, "param": {"user_id": uid}}
        json_data = json.dumps(json_data).encode()
        result = await asyncio.wait_for(
            self._executor.do_inference(self.inference_method, json_data),
            timeout=timeout,
        )

        assert result is not None, "user profile load should always returns a result"

        data: dict[str, Any] = json.loads(result.decode())

        # Text Profile
        if data.get("details_items", None):
            profile_details = UserProfileDetails(**rebuild_from_items(data["details_items"]))
        else:
            profile_details = None

        # Speaker Profile
        if data.get("speaker_vector", None):
            speaker_vector = data["speaker_vector"]
        else:
            speaker_vector = None

        # Face Profile
        # TODO: add face profile loading logic

        # User Runtime State (from local markdown)
        runtime_state = await self.load_runtime_state()

        return UserProfile(
            details=profile_details,
            runtime_state=runtime_state,
            speaker_vector=speaker_vector,
        )

    async def update(self, *, uid: str, persona: PersonaCache):
        """Async delta extraction -> in-memory patch."""
        if persona.profile_details:
            data = persona.profile_details.model_dump()
        else:
            data = {}

        update_time: str = persona.time
        chat_context = persona.messages
        if not chat_context:
            logger.info(f"[uid: {uid}] User Profile message is empty, UPDATE skip!")
            return

        new_turn = PersonaPluginsTemplate.apply_update_template(chat_context)
        delta = await self._aextract_delta(persona.profile_details_dump_value, new_turn)
        is_updated, updated_profile_details = self._apply_delta(update_time, data, delta)

        if is_updated:
            logger.info(f"[uid: {uid}] User Profile UPDATE success: {updated_profile_details}")
            persona.profile_details = UserProfileDetails(**updated_profile_details)
        else:
            logger.info(f"[uid: {uid}] User Profile output is empty, UPDATE skip!")

    async def save(self, *, uid: str, persona: PersonaCache, timeout: float | None = 15) -> None:
        """Save the text, voice, and face profile information of the specified user_id."""
        # Text Profile
        if persona.profile_details is not None:
            data = persona.profile_details.model_dump()
            details_items = flatten_items(uid, data)
        else:
            details_items = None

        # Voice Profile
        if persona.speaker_vector is not None:
            speaker_vector = persona.speaker_vector.tolist()
        else:
            speaker_vector = None

        # Face Profile
        # TODO: add face profile saving logic

        # Runtime State Markdown
        if persona.profile is not None and persona.profile.runtime_state is not None:
            try:
                md_path = await self.save_runtime_state(
                    runtime_state=persona.profile.runtime_state,
                )
                logger.info(f"User runtime state markdown save success: {md_path}")
            except Exception as e:
                logger.warning(f"User runtime state markdown save failed: {e}")

        # Skip saving if both details_items and speaker_vector are empty,
        # to avoid unnecessary VDB writes when only the runtime state markdown is updated.
        if (details_items is None or len(details_items) == 0) and speaker_vector is None:
            logger.info("User Profile VDB SAVE skip; runtime state markdown may already be saved.")
            return

        json_data = {
            "op": VectorRunnerOP.save,
            "param": {
                "user_id": uid,
                "details_items": details_items,
                "speaker_vector": speaker_vector,
            },
        }
        json_data = json.dumps(json_data).encode()
        result = await asyncio.wait_for(
            self._executor.do_inference(self.inference_method, json_data),
            timeout=timeout,
        )

        if result:
            logger.info(f"User Profile SAVE success: {result.decode()}")
        else:
            logger.warning("User Profile SAVE falied!")
