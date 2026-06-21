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
import importlib
import json
import os
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.utils.vdb import qdrant

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import SessionRuntime

importlib.import_module("alphaavatar.plugins.memory")


class MemoryConfig(BaseModel):
    """Configuration for the Memory plugin used in the agent."""

    plugin: str = Field(
        default="default",
        description="Avatar Memory plugin to use for memory management.",
    )

    # Memory Metadata
    search_context: int = Field(
        default=3,
        description="The number of contexts used for memory searches.",
    )
    recall_num: int = Field(
        default=10,
        description="The number of items to recall from the memory vector database.",
    )
    maximum_memory_num: int = Field(
        default=10,
        description="The maximum number of memory items to use",
    )

    # Memory init config
    init_config: dict = Field(
        default_factory=dict,
        description="Custom configuration parameters for the memory plugin.",
    )

    # Memory VDB Config
    vdb_config: dict = Field(
        default_factory=dict,
        description="Custom initialization parameters for the memory vdb backend (e.g., host, port, url, api_key, prefer_grpc).",
    )

    def model_post_init(self, __context):
        # Set MEMORY_VDB_CONFIG
        os.environ["MEMORY_VDB_CONFIG"] = json.dumps(self.vdb_config)
        if self.plugin == "default":
            # Ensure default Memory plugin is registered
            try:
                qdrant.get_client(
                    **self.vdb_config
                )  # Check if Qdrant client can be initialized with current config
                os.environ["MEMORY_VDB_TYPE"] = "qdrant"
            except ValueError:
                os.environ["MEMORY_VDB_TYPE"] = "lancedb"
        else:
            # TODO: Handle other memory plugins and their corresponding VDB types if needed
            pass

    def get_plugin(self, session_runtime: "SessionRuntime") -> MemoryBase:
        """Returns the Memory plugin instance based on the configuration."""
        return AvatarPlugin.get_avatar_plugin(
            AvatarModule.MEMORY,
            self.plugin,
            session_runtime=session_runtime,
            memory_search_context=self.search_context,
            memory_recall_num=self.recall_num,
            maximum_memory_num=self.maximum_memory_num,
            memory_init_config=self.init_config,
        )
