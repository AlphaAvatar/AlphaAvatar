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

from functools import cache
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.context import ContextManager
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.runtime import AvatarRuntime


@cache
def _load_context(name: str) -> None:
    matches = tuple(entry_points(group="alphaavatar.context", name=name))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one installed context {name!r}, found {len(matches)}")
    matches[0].load()


class ContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin: str = Field(default="default", min_length=1)
    init_config: dict[str, Any] = Field(default_factory=dict)

    def get_plugin(self, *, runtime: AvatarRuntime, avatar_config: AvatarConfig) -> ContextManager:
        from alphaavatar.agents.avatar.context import ContextManager
        from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin

        _load_context(self.plugin)
        manager = AvatarModulePlugin.create(
            AvatarModule.CONTEXT,
            self.plugin,
            runtime=runtime,
            avatar_config=avatar_config,
            init_config=self.init_config,
        )
        if not isinstance(manager, ContextManager):
            raise TypeError("A Context plugin must return ContextManager")

        return manager
