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

from alphaavatar.agents.runtime.plugin import AvatarModulePlugin

from .version import __version__

if TYPE_CHECKING:
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.agents.runtime.inference import InferenceRunner
    from alphaavatar.agents.tools import ToolBase


class MCPRemotePlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__("MCP", __version__, __name__)

    def inference_runners(self, config: AvatarConfig) -> tuple[type[InferenceRunner], ...]:
        from .inference import configure_inference_runners

        return configure_inference_runners(config)

    def get_plugin(
        self,
        *,
        runtime: AvatarRuntime,
        init_config: dict[str, Any],
        servers: dict[str, dict[str, Any]],
        vdb_config: dict[str, Any],
    ) -> ToolBase:
        from .inference import get_vdb_runner
        from .service import MCPToolService

        if init_config:
            raise ValueError("The default MCP tool has no init_config options")

        return MCPToolService(
            runtime=runtime,
            servers=servers,
            inference_method=get_vdb_runner(vdb_config).INFERENCE_METHOD,
        )
