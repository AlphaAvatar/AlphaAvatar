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

from typing import TYPE_CHECKING, Any

from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin

from .version import __version__

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.agents.status import StatusEmitter
    from alphaavatar.agents.tools import ToolBase


class DeepResearchToolPlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__("DeepResearch", __version__, __name__)

    def get_plugin(
        self,
        *,
        runtime: AvatarRuntime,
        init_config: dict[str, Any],
        status_emitter: StatusEmitter | None = None,
    ) -> ToolBase:
        from .service import DeepResearchService

        return DeepResearchService(
            runtime=runtime, init_config=init_config, status_emitter=status_emitter
        )


AvatarModulePlugin.register(AvatarModule.DEEPRESEARCH, "default", DeepResearchToolPlugin())
