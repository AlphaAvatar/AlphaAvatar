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

import importlib
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from alphaavatar.agents.character import CharacterTransport, VirtualCharacterSession
    from alphaavatar.agents.runtime import AvatarRuntime


class VirtualCharacterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin: str | None = Field(
        default=None,
        description="Avatar Virtual Character plugin to use for agent visually represents.",
    )
    init_config: dict[str, Any] = Field(
        default={}, description="Custom configuration parameters for the Virtual Character plugin."
    )

    def get_plugin(
        self, runtime: AvatarRuntime, *, transport: CharacterTransport
    ) -> VirtualCharacterSession | None:
        if self.plugin is None:
            return None

        from alphaavatar.agents.character import VirtualCharacterSession
        from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin

        importlib.import_module("alphaavatar.plugins.character")

        session = AvatarModulePlugin.create(
            AvatarModule.CHARACTER,
            self.plugin,
            runtime=runtime,
            transport=transport,
            init_config=self.init_config,
        )

        if not isinstance(session, VirtualCharacterSession):
            raise TypeError("Character factories must return VirtualCharacterSession")

        return session
