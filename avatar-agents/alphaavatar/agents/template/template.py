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

import json
from typing import TYPE_CHECKING, Any

from livekit.agents.llm import ChatItem, ChatMessage, ChatRole

from .prompts.avatar_system_prompts import AVATAR_SYSTEM_PROMPT

if TYPE_CHECKING:
    from alphaavatar.agents.persona import UserProfile


DEFAULT_SYSTEM_VALUE = "NONE"


class AvatarPromptTemplate:
    """
    A class to represent the prompt template for the Avatar Agent.

    This class encapsulates the prompt template used by the Avatar Agent, allowing for easy
    configuration and management of the prompt structure.
    """

    def __init__(
        self,
        # Instruction
        avatar_introduction: str,
        *,
        memory_content: str = DEFAULT_SYSTEM_VALUE,
        user_persona: str = DEFAULT_SYSTEM_VALUE,
        current_time: str = DEFAULT_SYSTEM_VALUE,
    ):
        # Instruction
        self._avatar_introduction = avatar_introduction
        self._memory_content = memory_content
        self._user_persona = user_persona
        self._current_time = current_time

    def instructions(
        self,
        *,
        avatar_introduction: str | None = None,
        memory_content: str | None = None,
        user_persona: str | None = None,
        current_time: str | None = None,
    ) -> str:
        """Initialize the system prompt for the Avatar Agent.

        Args:
            avatar_introduction (str): _description_

        Returns:
            str: _description_
        """
        if avatar_introduction:
            self._avatar_introduction = avatar_introduction

        if memory_content:
            self._memory_content = memory_content

        if user_persona:
            self._user_persona = user_persona

        if current_time:
            self._current_time = current_time

        return AVATAR_SYSTEM_PROMPT.format(
            avatar_introduction=self._avatar_introduction,
            memory_content=self._memory_content,
            user_persona=self._user_persona,
            current_time=self._current_time,
        )


class MemoryPluginsTemplate:
    @classmethod
    def apply_memory_search_template(
        cls, messages: list[ChatItem], *, filter_roles: list[ChatRole] | None = None
    ):
        """Apply the memory search template with the given keyword arguments."""
        if filter_roles is None:
            filter_roles = []
        memory_strings = []
        for msg in messages:
            if isinstance(msg, ChatMessage):
                role = msg.role
                if role in filter_roles:
                    continue

                msg_str = msg.text_content  # TODO: Handle different content types more robustly
                memory_strings.append(f"### {role}:\n{msg_str}")

        return "\n\n".join(memory_strings)


class PersonaPluginsTemplate:
    @classmethod
    def apply_update_template(cls, chat_context: list[ChatItem]) -> str:
        """Apply the profile update template with the given keyword arguments."""
        memory_strings = []
        for msg in chat_context:
            if isinstance(msg, ChatMessage):
                role = msg.role
                # TODO: Handle different content types more robustly
                if role not in ["user", "assistant"]:
                    continue

                msg_str = msg.text_content
                memory_strings.append(f"### {role}:\n{msg_str}")

        return "\n\n".join(memory_strings)

    @classmethod
    def apply_profile_template(
        cls,
        user_profiles: list[UserProfile],
        *,
        list_sep: str = ", ",
        sort_keys: bool = True,
        skip_empty: bool = True,
    ) -> str:
        """
        Render flat UserProfile(s) into a human-readable prompt for Avatar system.

        Args:
            user_profiles: list of UserProfile objects.
            list_sep: separator for list elements when rendering.
            sort_keys: whether to sort top-level keys alphabetically for stable output.
            skip_empty: skip None or empty-string values (and empty lists).

        Returns:
            A string ready to be used as part of a system prompt.
        """

        def _is_scalar(x: Any) -> bool:
            return isinstance(x, str | int | float | bool)

        def _format_value(val: Any) -> str:
            """Format value into display text:
            - scalar -> str(val)
            - list   -> join primitives as str, non-primitives as JSON
            - other  -> JSON
            """
            if _is_scalar(val):
                return str(val)

            if isinstance(val, list):
                if skip_empty and len(val) == 0:
                    return ""
                parts: list[str] = []
                for x in val:
                    if _is_scalar(x):
                        s = str(x)
                        if skip_empty and isinstance(x, str) and s.strip() == "":
                            continue
                        parts.append(s)
                    else:
                        parts.append(json.dumps(x, ensure_ascii=False))
                return list_sep.join(parts)

            # dict / object -> JSON
            return json.dumps(val, ensure_ascii=False)

        profile_blocks: list[str] = []

        for profile in user_profiles:
            data: dict[str, Any] = (
                profile.details.model_dump() if profile and profile.details else {}
            )

            keys = list(data.keys())
            if sort_keys:
                keys.sort()

            lines: list[str] = []
            for key in keys:
                item: dict = data[key]
                val = item.get("value", "")
                source = item.get("source", "")
                timestamp = item.get("timestamp", "")

                if skip_empty and (val is None or (isinstance(val, str) and val.strip() == "")):
                    continue

                display_val = _format_value(val)
                if skip_empty and display_val == "":
                    continue

                lines.append(
                    f"- {key}: {display_val} (updated at {timestamp}), source from: {source}"
                )

            profile_blocks.append("\n".join(lines))

        if len(profile_blocks) <= 1:
            return profile_blocks[0] if profile_blocks else ""

        return "\n\n".join(f"User {idx}\n{block}" for idx, block in enumerate(profile_blocks))
