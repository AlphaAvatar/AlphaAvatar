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

import importlib
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.avatar.voice import (
    STTBase,
    TranscriptionEvent,
    TTSBase,
    VADBase,
)
from alphaavatar.agents.interaction import InteractionRouterBase
from alphaavatar.agents.runtime import AvatarRuntime

importlib.import_module("alphaavatar.plugins.router")


class RouterConfig(BaseModel):
    """Interaction Router plugin configuration."""

    model_config = ConfigDict(extra="forbid")

    plugin: str = Field(
        default="default",
        description="Interaction Router plugin to use.",
    )

    pre_roll_sec: float = Field(
        default=0.3,
        ge=0.0,
        description="Audio retained before confirmed speech start.",
    )

    max_buffer_sec: float = Field(
        default=2.0,
        gt=0.0,
        description="Maximum raw audio retained by each router source.",
    )

    def get_plugin(
        self,
        *,
        runtime: AvatarRuntime,
        vad: VADBase | None = None,
        stt: STTBase | None = None,
        tts: TTSBase | None = None,
        on_transcription: Callable[[TranscriptionEvent], Awaitable[None] | None] | None = None,
    ) -> InteractionRouterBase:
        if self.max_buffer_sec < self.pre_roll_sec:
            raise ValueError("router.max_buffer_sec cannot be smaller than router.pre_roll_sec")

        return AvatarPlugin.get_avatar_plugin(
            AvatarModule.INTERACTION_ROUTER,
            self.plugin,
            runtime=runtime,
            # Voice
            vad=vad,
            stt=stt,
            tts=tts,
            on_transcription=on_transcription,
            pre_roll_sec=self.pre_roll_sec,
            max_buffer_sec=self.max_buffer_sec,
            # Visual
        )
