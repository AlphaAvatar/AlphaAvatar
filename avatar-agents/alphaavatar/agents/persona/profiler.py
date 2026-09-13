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

from alphaavatar.agents.runtime.capability import (
    AvatarCapabilityName,
    avatar_capability,
)

from .processor import PersonaProcessorBase


@avatar_capability(
    name=AvatarCapabilityName.PERSONA_PROFILE,
    description=(
        "Can maintain persistent user profiles from conversations and observed traits, "
        "and use them to personalize interactions across sessions."
    ),
)
class ProfilerProcessorBase(PersonaProcessorBase):
    @property
    def name(self) -> str:
        return "profiler"
