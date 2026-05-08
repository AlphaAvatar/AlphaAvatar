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
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from alphaavatar.agents.constants import DEFAULT_CONTEXT_VALUE


@dataclass
class InteractionMethod:
    """
    Describes what interaction modes are available in the current room/session.

    This should be derived from SessionMode + room_type + channel metadata.
    """

    room_type: str = "unknown"
    session_type: str = "unknown"

    text_input: bool = True
    text_output: bool = True
    audio_input: bool = False
    audio_output: bool = False
    video_input: bool = False
    video_output: bool = False

    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        enabled = []
        disabled = []

        modes = {
            "text input": self.text_input,
            "text output": self.text_output,
            "voice input": self.audio_input,
            "voice output": self.audio_output,
            "video input": self.video_input,
            "video output": self.video_output,
        }

        for name, is_enabled in modes.items():
            if is_enabled:
                enabled.append(name)
            else:
                disabled.append(name)

        lines = [
            f"- Room type: {self.room_type}",
            f"- Session type: {self.session_type}",
        ]

        lines.extend(
            [
                f"- Available interaction modes: {', '.join(enabled) if enabled else 'none'}",
                f"- Unavailable interaction modes: {', '.join(disabled) if disabled else 'none'}",
            ]
        )

        if self.notes:
            lines.append("- Notes:")
            lines.extend(f"  - {note}" for note in self.notes)

        return "\n".join(lines)


@dataclass
class TimeContext:
    """
    Describes the user's current time context.

    current_time should ideally be based on user's browser timezone.
    If browser timezone is unavailable, use metadata / env / server fallback.
    """

    current_time: str = DEFAULT_CONTEXT_VALUE
    current_timezone: str = DEFAULT_CONTEXT_VALUE
    timezone_source: str = "unknown"

    last_session_timezone: str = DEFAULT_CONTEXT_VALUE
    last_session_time: str = DEFAULT_CONTEXT_VALUE

    def render(self) -> str:
        return "\n".join(
            [
                f"- Current local time: {self.current_time}",
                f"- Current timezone: {self.current_timezone}",
                f"- Timezone source: {self.timezone_source}",
                f"- Last session timezone: {self.last_session_timezone}",
                f"- Last session time: {self.last_session_time}",
            ]
        )


@dataclass
class AvatarRuntimeContext:
    """
    Unified runtime context container.

    This object stores both system-level and turn-level context.
    The template layer decides where each field is injected.

    System-level:
    - interaction_method
    - user_persona
    - global_behavior_rules

    Turn-level:
    - time_context
    - memory_content
    - plan_content
    - reflection_content
    - turn_behavior_rules
    """

    interaction_method: InteractionMethod = field(default_factory=InteractionMethod)
    time_context: TimeContext = field(default_factory=TimeContext)

    # System-level, but may be refreshed during session when identity/persona is resolved.
    user_persona: str = DEFAULT_CONTEXT_VALUE
    global_behavior_rules: str = DEFAULT_CONTEXT_VALUE

    # Turn-level dynamic context.
    memory_content: str = DEFAULT_CONTEXT_VALUE
    reflection_content: str = DEFAULT_CONTEXT_VALUE
    plan_content: str = DEFAULT_CONTEXT_VALUE
    turn_behavior_rules: str = DEFAULT_CONTEXT_VALUE

    extra_context: dict[str, Any] = field(default_factory=dict)

    def render_extra_context(self) -> str:
        if not self.extra_context:
            return DEFAULT_CONTEXT_VALUE

        lines = []
        for key, value in self.extra_context.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)
