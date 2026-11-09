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
from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE
from alphaavatar.agents.runtime import InteractionMethod

from ...prompts.avatar_system_prompts import (
    AVATAR_SYSTEM_PROMPT,
    SPOKEN_RESPONSE_STYLE,
    TEXT_RESPONSE_STYLE,
)
from ...prompts.xml_protocol_prompts import XML_PROTOCOL_PROMPT


def render_avatar_instructions(
    avatar_introduction: str,
    *,
    interaction_method: InteractionMethod,
    stable_persona: str | None = None,
    stable_behavior_rules: str | None = None,
) -> str:
    prompt = AVATAR_SYSTEM_PROMPT.format(
        avatar_introduction=avatar_introduction,
        interaction_method=interaction_method.render(),
        response_style=SPOKEN_RESPONSE_STYLE
        if interaction_method.audio_output
        else TEXT_RESPONSE_STYLE,
        stable_persona=stable_persona or DEFAULT_SYSTEM_VALUE,
        stable_behavior_rules=stable_behavior_rules or DEFAULT_SYSTEM_VALUE,
    ).strip()
    return f"{prompt}\n\n{XML_PROTOCOL_PROMPT}"
