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
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin

if TYPE_CHECKING:
    from alphaavatar.agents.router import InteractionRouterBase
    from alphaavatar.agents.runtime import AvatarRuntime

importlib.import_module("alphaavatar.plugins.router")


class RouterConfig(BaseModel):
    """Interaction Router plugin selection and plugin-owned options."""

    model_config = ConfigDict(extra="forbid")

    plugin: str = Field(default="default", description="Interaction Router plugin to use.")
    init_config: dict[str, Any] = Field(default_factory=dict)

    def get_plugin(self, *, runtime: AvatarRuntime) -> InteractionRouterBase:
        return AvatarModulePlugin.create(
            AvatarModule.ROUTER,
            self.plugin,
            runtime=runtime,
            init_config=self.init_config,
        )
