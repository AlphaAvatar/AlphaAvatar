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
from typing import Literal

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.memory import MemoryBase


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class MemoryConfig:
    """Configuration for the Memory plugin used in the agent."""

    # Memory Metadata
    memory_search_context: int = Field(
        default=3,
        description="The number of contexts used for memory searches.",
    )
    memory_recall_session: int = Field(
        default=1,
        description="Number of sessions to recall from memory.",
    )
    maximum_memory_items: int = Field(
        default=10,
        description="The maximum number of memory items to use",
    )

    # Memory plugin config
    memory_plugin: Literal["mem0"] = Field(
        default="mem0",
        description="Avatar Memory plugin to use for memory management.",
    )
    memory_mode: Literal["local", "client"] = Field(
        default="client",
        description="Mode of memory operation, either 'local' for local storage or 'client' for remote client operations.",
    )
    memory_init_config: dict | None = Field(
        default=None,
        description="Custom configuration parameters for the memory plugin.",
    )

    def get_memory_plugin(self, *, avatar_id: str, avater_name: str) -> MemoryBase:
        """Returns the Memory plugin instance based on the configuration."""
        return AvatarPlugin.get_avatar_plugin(
            AvatarModule.MEMORY,
            self.memory_plugin,
            avatar_id=avatar_id,
            avater_name=avater_name,
            memory_search_context=self.memory_search_context,
            memory_recall_session=self.memory_recall_session,
            maximum_memory_items=self.maximum_memory_items,
            memory_init_config=self.memory_init_config,
        )
