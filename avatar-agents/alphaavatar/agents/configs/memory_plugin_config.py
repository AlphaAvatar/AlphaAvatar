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

from alphaavatar.agents.memory import MemoryBase


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class MemoryConfig:
    """Configuration for the Memory plugin used in the agent."""

    # Memory Metadata
    memory_search_length: int = Field(
        default=4,
        description="The number of contexts used for memory searches.",
    )
    memory_recall_session: int = Field(
        default=14,
        description="Number of sessions to recall from memory.",
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
        match self.memory_plugin:
            case "mem0":
                try:
                    from mem0 import AsyncMemory, AsyncMemoryClient
                    from mem0.configs.base import MemoryConfig

                    from alphaavatar.plugins.memory.mem0 import Memory as Mem0Memory
                except ImportError:
                    raise ImportError(
                        "The 'mem0' Memory plugin is required but is not installed.\n"
                        "To fix this, install the optional dependency: `pip install alphaavatar-plugins-memory`"
                    )

                if self.memory_mode == "client":
                    client = AsyncMemoryClient()
                else:
                    if self.memory_init_config:
                        config = MemoryConfig(**self.memory_init_config)
                        client = AsyncMemory(config=config)
                    else:
                        client = AsyncMemory()
                return Mem0Memory(
                    avater_name=avater_name,
                    avatar_id=avatar_id,
                    memory_search_length=self.memory_search_length,
                    memory_recall_session=self.memory_recall_session,
                    client=client,
                )
            case _:
                raise ValueError(f"Unsupported memory plugin: {self.memory_plugin}")
