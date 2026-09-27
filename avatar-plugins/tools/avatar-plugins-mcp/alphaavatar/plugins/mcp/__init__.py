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
import json
import os

from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.inference import register_inference_runner_bootstrap
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
from alphaavatar.agents.tools import MCPAPI

from .inference import configure_inference_runners
from .log import logger
from .mcp_host import MCPHost
from .version import __version__

__all__ = ["__version__"]


class MCPRemotePlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)

    def get_plugin(self, runtime: AvatarRuntime, init_config: dict, *args, **kwargs) -> MCPAPI:
        try:
            status_emitter = kwargs.pop("status_emitter", None)
            servers = json.loads(os.getenv("MCP_SERVERS", "{}"))
            mcp_host = MCPHost(runtime=runtime, servers=servers, **init_config, **kwargs)
            return MCPAPI(mcp_host, status_emitter=status_emitter)
        except Exception as exc:
            raise ImportError(
                "The MCP plugin failed to initialize. "
                "Install the optional dependency: `pip install alphaavatar-plugins-mcp`. "
                f"Original error: {exc}"
            ) from exc


# Plugin register
AvatarModulePlugin.register(
    AvatarModule.MCP,
    "default",
    MCPRemotePlugin(),
)

# Inference Runners
register_inference_runner_bootstrap(
    "alphaavatar.plugins.mcp",
    configure_inference_runners,
)
