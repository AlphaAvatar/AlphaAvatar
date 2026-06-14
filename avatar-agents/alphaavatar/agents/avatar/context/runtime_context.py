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
from alphaavatar.agents.utils.time_utils import TimeStamp


@dataclass
class InteractionMethod:
    """
    Describes what interaction modes are available in the current room/session.

    This should be derived from SessionMode + room_type + channel metadata.
    Keep this aligned with LiveKit RoomOptions:
    - text_input
    - audio_input
    - video_input
    - audio_output
    - text_output
    """

    room_type: str = "unknown"
    session_type: str = "unknown"

    text_input: bool = True
    audio_input: bool = False
    video_input: bool = False

    audio_output: bool = False
    text_output: bool = True

    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        input_modes = []
        output_modes = []
        unavailable_modes = []

        if self.text_input:
            input_modes.append("text messages")
        else:
            unavailable_modes.append("text input")

        if self.audio_input:
            input_modes.append("spoken voice / microphone audio")
        else:
            unavailable_modes.append("voice input")

        if self.video_input:
            input_modes.append("visual input from camera or screen sharing")
        else:
            unavailable_modes.append("visual input")

        if self.text_output:
            output_modes.append("text responses / transcription-style output")
        else:
            unavailable_modes.append("text output")

        if self.audio_output:
            output_modes.append("spoken voice responses")
        else:
            unavailable_modes.append("voice output")

        lines = [
            f"- Room type: {self.room_type}",
            f"- Session type: {self.session_type}",
            "",
            "- Supported user input:",
            f"  - {', '.join(input_modes) if input_modes else 'none'}",
            "- Supported assistant output:",
            f"  - {', '.join(output_modes) if output_modes else 'none'}",
            "- Unavailable modalities:",
            f"  - {', '.join(unavailable_modes) if unavailable_modes else 'none'}",
            "",
            "- Interaction rules:",
        ]

        if self.text_input:
            lines.append("  - The user may send text messages. Treat text as a valid user turn.")
        else:
            lines.append("  - Do not wait for or ask the user to type text.")

        if self.audio_input:
            lines.append(
                "  - The user may speak through the microphone. Treat transcribed speech as user input."
            )
        else:
            lines.append("  - Do not assume microphone or spoken input is available.")

        if self.video_input:
            lines.append(
                "  - Visual input is enabled for this session. "
                "Visual evidence may be provided in one of two ways: "
                "sampled visual frames attached to the current user message, or live realtime visual input from the active model/session. "
                "If sampled frames are attached, treat them as visual evidence for the current turn. "
                "If realtime visual input is active, treat the current live visual context as visual evidence for the current turn. "
                "When current visual evidence is available, do not say that you cannot see; answer based on what is visible and state uncertainty when details are unclear. "
                "If no current visual evidence is available for the turn, do not invent visual details; say that no current visual context is available."
            )
        else:
            lines.append(
                "  - Visual input is not enabled for this session. "
                "Do not claim to see the user, camera, screen, objects, gestures, screen content, or surroundings."
            )

        if self.audio_output:
            lines.append(
                "  - Keep responses suitable for spoken delivery: concise, natural, and easy to follow."
            )
        else:
            lines.append("  - The assistant cannot speak in this session; respond in text only.")

        if self.text_output:
            lines.append("  - Text output is available. Use clear formatting when helpful.")
        else:
            lines.append(
                "  - Avoid relying on visual text formatting because text output is unavailable."
            )

        if self.notes:
            lines.append("")
            lines.append("- Additional notes:")
            lines.extend(f"  - {note}" for note in self.notes)

        return "\n".join(lines)


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
    - timestamp
    - memory_content
    - plan_content
    - reflection_content
    - turn_behavior_rules
    """

    interaction_method: InteractionMethod = field(default_factory=InteractionMethod)
    timestamp: TimeStamp = field(default_factory=TimeStamp)

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
