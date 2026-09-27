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
from alphaavatar.agents.runtime.capability import AvatarCapability
from alphaavatar.agents.utils.time import ParticipantTimeContext

from .prompts.avatar_system_prompts import AVATAR_SYSTEM_PROMPT
from .prompts.runtime_context_prompts import RUNTIME_CONTEXT_PROMPT
from .prompts.xlm_protocol_prompts import XML_PROTOCOL_PROMPT


def _xml_text(value: object | None) -> str:
    return escape(str(value or DEFAULT_SYSTEM_VALUE))


def _render_capabilities(capabilities: tuple[AvatarCapability, ...]) -> str:
    return (
        "\n".join(
            f"- {capability.id}: {capability.model_description}" for capability in capabilities
        )
        or DEFAULT_SYSTEM_VALUE
    )


def _render_participant_time(participant_time: dict[str, ParticipantTimeContext]) -> str:
    if not participant_time:
        return DEFAULT_SYSTEM_VALUE

    return "\n".join(
        f"- User {_xml_text(p.user_id or f'participant:{p.participant_id}')}: "
        f"{_xml_text(p.user_time.time_str)}"
        for p in participant_time.values()
    )


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
        internal_capabilities: tuple[AvatarCapability, ...] = (),
        stable_persona: str = DEFAULT_SYSTEM_VALUE,
        stable_behavior_rules: str = DEFAULT_SYSTEM_VALUE,
    ) -> None:
        self._avatar_introduction = avatar_introduction
        self._interaction_method = interaction_method or InteractionMethod()
        self._internal_capabilities = _render_capabilities(internal_capabilities)
        self._stable_persona = stable_persona
        self._stable_behavior_rules = stable_behavior_rules

    def instructions(
        self,
        *,
        stable_persona: str | None = None,
        stable_behavior_rules: str | None = None,
    ) -> str:
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
            # static
            avatar_introduction=self._avatar_introduction,
            interaction_method=self._interaction_method.render(),
            internal_capabilities=self._internal_capabilities,
            # half-dynamic
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
            participant_time=_render_participant_time(context_runtime.participant_time),
            memory_content=_xml_text(context_runtime.memory_content),
            plan_content=_xml_text(context_runtime.plan_content),
            reflection_content=_xml_text(context_runtime.reflection_content),
            behavior_rules=_xml_text(context_runtime.turn_behavior_rules),
        )
