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
from xml.sax.saxutils import escape

from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE
from alphaavatar.agents.runtime import StateRuntime
from alphaavatar.agents.utils.time import ParticipantTimeContext

from ...prompts.runtime_context_prompts import RUNTIME_CONTEXT_PROMPT


def _xml_text(value: object | None) -> str:
    return escape(str(value or DEFAULT_SYSTEM_VALUE))


def _render_participant_time(participant_time: dict[str, ParticipantTimeContext]) -> str:
    if not participant_time:
        return DEFAULT_SYSTEM_VALUE

    return "\n".join(
        f"- User {_xml_text(p.user_id or f'participant:{p.participant_id}')}: "
        f"{_xml_text(p.user_time.time_str)}"
        for p in participant_time.values()
    )


def render_runtime_context(state: StateRuntime) -> str:
    return RUNTIME_CONTEXT_PROMPT.format(
        participant_time=_render_participant_time(state.participant_time),
        memory_content=_xml_text(state.memory_content),
        plan_content=_xml_text(state.plan_content),
        reflection_content=_xml_text(state.reflection_content),
        behavior_rules=_xml_text(state.turn_behavior_rules),
    )
