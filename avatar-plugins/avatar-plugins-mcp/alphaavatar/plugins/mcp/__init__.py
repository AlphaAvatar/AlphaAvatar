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
        mcp_init_config: dict,
        *args,
        **kwargs,
    ) -> MCPAPI:
        try:
            status_emitter = kwargs.pop("status_emitter", None)

            servers = os.getenv("MCP_SERVERS", "{}")
            servers = json.loads(servers)

            mcp_host = MCPHost(
                servers=servers,
                **mcp_init_config,
                **kwargs,
            )
            return MCPAPI(mcp_host, status_emitter=status_emitter)
        except Exception as e:
            raise ImportError(
                "The MCP plugin is required but failed to initialize.\n"
                "To fix this, install the optional dependency: "
                "`pip install alphaavatar-plugins-mcp`\n"
                f"Original error: {e}"
            ) from e


def bootstrap_inference_runners() -> None:
    """
    Plugin-owned runner bootstrap.

    Called by AlphaAvatar core after AvatarConfig is parsed.
    """
    mcp_vdb_type = os.getenv("MCP_VDB_TYPE", "lancedb")

    if mcp_vdb_type == "lancedb":
        from .runner import LanceDBRunner

        os.environ["MCP_INFERENCE_METHOD"] = LanceDBRunner.INFERENCE_METHOD
        AvatarPlugin.register_inference_runner_once(LanceDBRunner)
        return

    logger.warning("Unsupported MCP_VDB_TYPE=%r", mcp_vdb_type)


# Plugin register
AvatarPlugin.register_avatar_plugin(
    AvatarModule.MCP,
    "default",
    MCPRemotePlugin(),
)

# Runner bootstrap register
AvatarPlugin.register_inference_runner_bootstrap(
    "alphaavatar.plugins.mcp",
    bootstrap_inference_runners,
)
