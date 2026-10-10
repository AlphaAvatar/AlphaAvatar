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

from typing import TYPE_CHECKING, Any

from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin

from .version import __version__

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.agents.status import StatusBase


class DefaultStatusPlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__("Status", __version__, __name__)

    def get_plugin(
        self, *, runtime: AvatarRuntime, enabled: bool = True, init_config: dict[str, Any]
    ) -> StatusBase:
        from .config import StatusRuntimeConfig
        from .runtime import StatusRuntime

        return StatusRuntime(
            runtime=runtime, enabled=enabled, config=StatusRuntimeConfig.model_validate(init_config)
        )


AvatarModulePlugin.register(AvatarModule.STATUS, "default", DefaultStatusPlugin())
