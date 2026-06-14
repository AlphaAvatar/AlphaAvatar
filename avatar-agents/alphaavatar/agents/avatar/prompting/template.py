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

from ..context.runtime_context import AvatarRuntimeContext, InteractionMethod
from .prompts.avatar_system_prompts import AVATAR_SYSTEM_PROMPT
from .prompts.runtime_context_prompts import RUNTIME_CONTEXT_PROMPT

if TYPE_CHECKING:
    from alphaavatar.agents.persona import UserProfile


class AvatarSysPromptTemplate:
    """
    Static system prompt template for the Avatar Agent.

    This template should only contain stable information to improve prefix cache hit rate.
    Dynamic per-turn context such as memory, current time, plan, and reflection should not
    be rendered here.
    """

    def __init__(
        self,
        avatar_introduction: str,
        *,
        interaction_method: InteractionMethod | None = None,
        stable_persona: str = DEFAULT_SYSTEM_VALUE,
        stable_behavior_rules: str = DEFAULT_SYSTEM_VALUE,
    ):
        self._avatar_introduction = avatar_introduction
        self._interaction_method = interaction_method or InteractionMethod()
        self._stable_persona = stable_persona
        self._stable_behavior_rules = stable_behavior_rules

    def instructions(
        self,
        *,
        avatar_introduction: str | None = None,
        interaction_method: InteractionMethod | None = None,
        stable_persona: str | None = None,
        stable_behavior_rules: str | None = None,
    ) -> str:
        if avatar_introduction:
            self._avatar_introduction = avatar_introduction

        if interaction_method:
            self._interaction_method = interaction_method

        if stable_persona is not None:
            self._stable_persona = stable_persona or DEFAULT_SYSTEM_VALUE

        if stable_behavior_rules is not None:
            self._stable_behavior_rules = stable_behavior_rules or DEFAULT_SYSTEM_VALUE

        return AVATAR_SYSTEM_PROMPT.format(
            avatar_introduction=self._avatar_introduction,
            interaction_method=self._interaction_method.render(),
            stable_persona=self._stable_persona,
            stable_behavior_rules=self._stable_behavior_rules,
        )


class RuntimeContextTemplate:
    """
    Per-turn runtime context template.

    Only dynamic current-turn information should be rendered here.
    Stable persona should stay in the system prompt.
    """

    def render(
        self,
        *,
        runtime_context: AvatarRuntimeContext,
    ) -> str:
        current_time = runtime_context.timestamp.time_str
        memory_content = runtime_context.memory_content
        plan_content = runtime_context.plan_content
        reflection_content = runtime_context.reflection_content
        behavior_rules = runtime_context.turn_behavior_rules

        return RUNTIME_CONTEXT_PROMPT.format(
            current_time=current_time or DEFAULT_SYSTEM_VALUE,
            memory_content=memory_content or DEFAULT_SYSTEM_VALUE,
            plan_content=plan_content or DEFAULT_SYSTEM_VALUE,
            reflection_content=reflection_content or DEFAULT_SYSTEM_VALUE,
            behavior_rules=behavior_rules or DEFAULT_SYSTEM_VALUE,
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
    def _render_flat_model(
        cls,
        data: dict[str, Any],
        *,
        list_sep: str = ", ",
        sort_keys: bool = True,
        skip_empty: bool = True,
    ) -> list[str]:
        keys = list(data.keys())
        if sort_keys:
            keys.sort()

        lines: list[str] = []

        for attr in keys:
            value = data[attr]
            if value is None:
                continue

            if isinstance(value, list):
                attr_values = []
                for v in value:
                    if not isinstance(v, dict):
                        continue
                    val = v.get("value", "")
                    source = v.get("source", "")
                    timestamp = v.get("timestamp", "")
                    attr_values.append(f"{val} (updated at {timestamp}) | source from: {source}")
                if attr_values:
                    lines.append(f"- {attr}: {list_sep.join(attr_values)}")
            elif isinstance(value, dict):
                val = value.get("value", "")
                source = value.get("source", "")
                timestamp = value.get("timestamp", "")

                if skip_empty and (val is None or (isinstance(val, str) and val.strip() == "")):
                    continue

                lines.append(f"- {attr}: {val} (updated at {timestamp}) | source from: {source}")
            else:
                if skip_empty and (
                    value is None or (isinstance(value, str) and value.strip() == "")
                ):
                    continue

                lines.append(f"- {attr}: {value}")

        return lines

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
    def apply_system_template(
        cls,
        user_profiles: list[UserProfile],
        *,
        list_sep: str = ", ",
        sort_keys: bool = True,
        skip_empty: bool = True,
    ) -> str:
        """
        Render UserProfile(s) into a human-readable prompt for Avatar system.

        Includes:
        - Runtime state: system-observed login/session state
        - Details: LLM-extracted profile details
        """
        profile_blocks: list[str] = []

        for profile in user_profiles:
            sections: list[str] = []

            if profile and profile.runtime_state:
                runtime_data = profile.runtime_state.model_dump()
                runtime_lines = cls._render_flat_model(
                    runtime_data,
                    list_sep=list_sep,
                    sort_keys=sort_keys,
                    skip_empty=skip_empty,
                )
                if runtime_lines:
                    sections.append(
                        "### Runtime state\n"
                        "System-observed login/session state. Use subtly; do not mention unless helpful.\n"
                        + "\n".join(runtime_lines)
                    )

            if profile and profile.details:
                details_data = profile.details.model_dump()
                details_lines = cls._render_flat_model(
                    details_data,
                    list_sep=list_sep,
                    sort_keys=sort_keys,
                    skip_empty=skip_empty,
                )
                if details_lines:
                    sections.append(
                        "### User profile details\n"
                        "LLM-extracted long-term user profile.\n" + "\n".join(details_lines)
                    )

            if sections:
                profile_blocks.append("\n\n".join(sections))

        if len(profile_blocks) <= 1:
            return profile_blocks[0] if profile_blocks else ""

        return "\n\n".join(f"User {idx}\n{block}" for idx, block in enumerate(profile_blocks))
