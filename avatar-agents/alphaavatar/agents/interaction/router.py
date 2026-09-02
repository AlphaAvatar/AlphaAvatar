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

from abc import ABC
from dataclasses import dataclass
from typing import TYPE_CHECKING

from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.perception import PerceptionRuntime

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.voice import (
        STTBase,
        TTSBase,
        VADBase,
    )


@dataclass(frozen=True, slots=True)
class InteractionRouterDependencies:
    runtime: AvatarRuntime
    vad: VADBase | None = None
    stt: STTBase | None = None
    tts: TTSBase | None = None


class InteractionRouterBase(AvatarRuntimePlugin, ABC):
    """Session-scoped interaction routing plugin."""

    def __init__(self, *, runtime: AvatarRuntime) -> None:
        self.runtime = runtime

    @property
    def perception_runtime(self) -> PerceptionRuntime:
        return self.runtime.perception
