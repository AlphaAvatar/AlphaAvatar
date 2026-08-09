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

from xml.sax.saxutils import escape

from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE
from alphaavatar.agents.runtime import ContextRuntime, InteractionMethod

from .prompts.avatar_system_prompts import AVATAR_SYSTEM_PROMPT
from .prompts.runtime_context_prompts import RUNTIME_CONTEXT_PROMPT
from .prompts.xlm_protocol_prompts import XML_PROTOCOL_PROMPT


def _xml_text(value: object | None) -> str:
    return escape(str(value or DEFAULT_SYSTEM_VALUE))


class AvatarSysPromptTemplate:
    """
    Stable system prompt template.

    Dynamic time, memory, plan, reflection and per-turn behavior rules belong
    to RuntimeContextTemplate and are injected for the current answer only.
    """

    def __init__(
        self,
        avatar_introduction: str,
        *,
        interaction_method: InteractionMethod | None = None,
        stable_persona: str = DEFAULT_SYSTEM_VALUE,
        stable_behavior_rules: str = DEFAULT_SYSTEM_VALUE,
    ) -> None:
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
        introduction = (
            self._avatar_introduction if avatar_introduction is None else avatar_introduction
        )
        method = self._interaction_method if interaction_method is None else interaction_method
        persona = (
            self._stable_persona
            if stable_persona is None
            else stable_persona or DEFAULT_SYSTEM_VALUE
        )
        behavior_rules = (
            self._stable_behavior_rules
            if stable_behavior_rules is None
            else stable_behavior_rules or DEFAULT_SYSTEM_VALUE
        )

        base_prompt = AVATAR_SYSTEM_PROMPT.format(
            avatar_introduction=introduction,
            interaction_method=method.render(),
            stable_persona=persona,
            stable_behavior_rules=behavior_rules,
        ).strip()

        return f"{base_prompt}\n\n{XML_PROTOCOL_PROMPT}"


class RuntimeContextTemplate:
    """Render dynamic current-answer-only runtime context."""

    def render(
        self,
        *,
        context_runtime: ContextRuntime,
    ) -> str:
        return RUNTIME_CONTEXT_PROMPT.format(
            current_time=_xml_text(context_runtime.timestamp.time_str),
            memory_content=_xml_text(context_runtime.memory_content),
            plan_content=_xml_text(context_runtime.plan_content),
            reflection_content=_xml_text(context_runtime.reflection_content),
            behavior_rules=_xml_text(context_runtime.turn_behavior_rules),
        )
