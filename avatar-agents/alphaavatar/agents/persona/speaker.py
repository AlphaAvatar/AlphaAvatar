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

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import (
    AvatarCapability,
    AvatarCapabilityName,
    avatar_capability,
)
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.core.perception import PerceptionRuntime

if TYPE_CHECKING:
    from .base import PersonaBase


@avatar_capability(
    name=AvatarCapabilityName.PERSONA_SPEAKER_RECOGNITION,
    description=(
        "Can recognize previously known users from their voice and infer speaker "
        "attributes when speech audio is available."
    ),
)
class SpeakerStreamBase(ABC):
    """
    Session-scoped streaming speaker perception runtime.

    It consumes routed speech observations from PerceptionRuntime and must not
    own VAD, STT or RTC input.
    """

    capabilities: tuple[AvatarCapability, ...]

    def __init__(self, *, runtime: AvatarRuntime, activity_persona: PersonaBase) -> None:
        self.runtime = runtime
        self.activity_persona = activity_persona

    @property
    def perception_runtime(self) -> PerceptionRuntime:
        return self.runtime.perception

    @property
    def inference_executor(self) -> InferenceExecutor:
        return self.runtime.inference

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
