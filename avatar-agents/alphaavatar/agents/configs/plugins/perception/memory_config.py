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
from typing import Any

from pydantic import BaseModel, Field

from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
from alphaavatar.agents.utils.vdb.config import snapshot_vdb_config


class MemoryConfig(BaseModel):
    """Configuration for the Memory plugin used in the agent."""

    plugin: str = Field(
        default="default", description="Avatar Memory plugin to use for memory management."
    )

    # Memory Metadata
    maximum_memory_num: int = Field(
        default=10, description="The maximum number of memory items to use"
    )

    # Memory init config
    init_config: dict = Field(
        default_factory=dict, description="Custom configuration parameters for the memory plugin."
    )

    # Memory VDB Config
    vdb_config: dict = Field(
        default_factory=dict,
        repr=False,
        description="Custom initialization parameters for the memory vdb backend (e.g., host, port, url, api_key, prefer_grpc).",
    )

    def model_post_init(self, __context: Any) -> None:
        self.vdb_config = snapshot_vdb_config(self.vdb_config)

    def runner_config(self) -> dict[str, Any]:
        """What the plugin's inference runners read at launch; it holds credentials."""
        return self.vdb_config

    def get_plugin(self, runtime: AvatarRuntime, avatar_id: str) -> MemoryBase:
        """Returns the Memory plugin instance based on the configuration."""
        return AvatarModulePlugin.create(
            AvatarModule.MEMORY,
            self.plugin,
            runtime=runtime,
            avatar_id=avatar_id,
            maximum_memory_num=self.maximum_memory_num,
            vdb_config=self.vdb_config,
            init_config=self.init_config,
        )
