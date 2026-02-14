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
from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.tools import MCPAPI

from .log import logger
from .mcp_host import MCPHost
from .version import __version__

__all__ = [
    "__version__",
]


class MCPRemotePlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(
        self,
        urls: list[str],
        mcp_init_config: dict,
        *args,
        **kwargs,
    ) -> MCPHost:
        try:
            mcp_host = MCPHost(urls=urls, **mcp_init_config, **kwargs)
            mcp_api = MCPAPI(mcp_host)
            return mcp_api
        except Exception:
            raise ImportError(
                "The MCP plugin is required but is not installed.\n"
                "To fix this, install the optional dependency: `pip install alphaavatar-plugins-mcp`"
            )


# plugin init
AvatarPlugin.register_avatar_plugin(AvatarModule.MCP, "default", MCPRemotePlugin())
