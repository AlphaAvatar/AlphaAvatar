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

from typing import TYPE_CHECKING, Any

from livekit.agents.llm import ChatItem, ChatMessage, ChatRole, FunctionCall, FunctionCallOutput

from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE
from alphaavatar.agents.memory import MemoryType

from .prompts.avatar_system_prompts import AVATAR_SYSTEM_PROMPT

if TYPE_CHECKING:
    from alphaavatar.agents.persona import UserProfile


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
    def apply_update_template(cls, chat_context: list[ChatItem], memory_type: MemoryType) -> str:
        """Apply the profile update template with the given keyword arguments."""
        memory_strings = []
        for msg in chat_context:
            if isinstance(msg, ChatMessage):
                role = msg.role
                # TODO: Handle different content types more robustly
                if memory_type == MemoryType.CONVERSATION and role not in ["user", "assistant"]:
                    continue

                msg_str = msg.text_content
                memory_strings.append(f"### {role}:\n{msg_str}")
            elif isinstance(msg, FunctionCall):
                role = f"assistant call function [{msg.name}]"
                msg_str = f"Function arguments: {msg.arguments}"
                memory_strings.append(f"### {role}:\n{msg_str}")
            elif isinstance(msg, FunctionCallOutput):
                role = f"function [{msg.name}] output"
                msg_str = msg.output
                memory_strings.append(f"### {role}:\n{msg_str}")

        return "\n\n".join(memory_strings)

    @classmethod
    def apply_search_template(
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
        profile_blocks: list[str] = []

        for profile in user_profiles:
            data: dict[str, Any] = (
                profile.details.model_dump() if profile and profile.details else {}
            )

            profile_attr = list(data.keys())
            if sort_keys:
                profile_attr.sort()

            lines: list[str] = []
            for attr in profile_attr:
                value: dict | list | None = data[attr]
                if value is None:
                    continue

                if isinstance(value, list):
                    attr_values = []
                    for v in value:
                        val = v.get("value", "")
                        source = v.get("source", "")
                        timestamp = v.get("timestamp", "")
                        attr_values.append(
                            f"{val} (updated at {timestamp}) | source from: {source}"
                        )
                    lines.append(f"- {attr}: {list_sep.join(attr_values)}")
                else:
                    val = value.get("value", "")
                    source = value.get("source", "")
                    timestamp = value.get("timestamp", "")

                    if skip_empty and (val is None or (isinstance(val, str) and val.strip() == "")):
                        continue

                    lines.append(
                        f"- {attr}: {val} (updated at {timestamp}) | source from: {source}"
                    )

            profile_blocks.append("\n".join(lines))

        if len(profile_blocks) <= 1:
            return profile_blocks[0] if profile_blocks else ""

        return "\n\n".join(f"User {idx}\n{block}" for idx, block in enumerate(profile_blocks))
