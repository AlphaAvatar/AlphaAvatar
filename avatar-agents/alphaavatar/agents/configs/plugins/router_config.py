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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.router import (
    InteractionRouterBase,
    InteractionRouterDependencies,
)

importlib.import_module("alphaavatar.plugins.router")


class RouterConfig(BaseModel):
    """Interaction Router plugin selection and plugin-owned options."""

    model_config = ConfigDict(extra="forbid")

    plugin: str = Field(
        default="default",
        description="Interaction Router plugin to use.",
    )
    init_config: dict[str, Any] = Field(default_factory=dict)

    def get_plugin(
        self,
        *,
        dependencies: InteractionRouterDependencies,
    ) -> InteractionRouterBase:
        return AvatarPlugin.get_avatar_plugin(
            AvatarModule.ROUTER,
            self.plugin,
            dependencies=dependencies,
            init_config=self.init_config,
        )
