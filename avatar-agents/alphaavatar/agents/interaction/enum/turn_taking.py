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
from enum import StrEnum


class InteractionEntityKind(StrEnum):
    AVATAR = "avatar"
    PERSON = "person"
    GROUP = "group"
    UNKNOWN = "unknown"


class AddressingMode(StrEnum):
    DIRECT = "direct"
    GROUP = "group"
    BROADCAST = "broadcast"
    UNKNOWN = "unknown"


class AddressingEvidenceKind(StrEnum):
    INVOCATION = "invocation"
    VISUAL_ORIENTATION = "visual_orientation"
    SEMANTIC = "semantic"
    CONVERSATION_FOCUS = "conversation_focus"
    EXPLICIT = "explicit"


class TurnTakingMode(StrEnum):
    VISUAL_ONLY = "visual_only"
    AUDIO_ONLY = "audio_only"
    AUDIO_VISUAL = "audio_visual"


class TurnTakingAction(StrEnum):
    HOLD = "hold"
    COMMIT = "commit"
    PASSIVE = "passive"
    INTERRUPT = "interrupt"
    PROACTIVE_CHECK = "proactive_check"
    CANCEL = "cancel"
