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

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.memory import MemoryBase

importlib.import_module("alphaavatar.plugins.memory")


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class MemoryConfig:
    """Configuration for the Memory plugin used in the agent."""

    # Memory Metadata
    memory_search_context: int = Field(
        default=3,
        description="The number of contexts used for memory searches.",
    )
    memory_recall_num: int = Field(
        default=10,
        description="The number of items to recall from the memory vector database.",
    )
    maximum_memory_num: int = Field(
        default=10,
        description="The maximum number of memory items to use",
    )

    # Memory plugin config
    memory_plugin: str = Field(
        default="mem0_client",
        description="Avatar Memory plugin to use for memory management.",
    )
    memory_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the memory plugin.",
    )

    def get_memory_plugin(self, *, avatar_id: str, activate_time: str) -> MemoryBase:
        """Returns the Memory plugin instance based on the configuration."""
        return AvatarPlugin.get_avatar_plugin(
            AvatarModule.MEMORY,
            self.memory_plugin,
            avatar_id=avatar_id,
            activate_time=activate_time,
            memory_search_context=self.memory_search_context,
            memory_recall_num=self.memory_recall_num,
            maximum_memory_num=self.maximum_memory_num,
            memory_init_config=self.memory_init_config,
        )
