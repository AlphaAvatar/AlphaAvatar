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
from livekit.agents import Plugin

from alphaavatar.agents import AvatarModule, AvatarPlugin

from .log import logger
from .mem0 import Mem0Memory
from .version import __version__

__all__ = [
    "__version__",
]


class MemoryMem0Plugin(Plugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self) -> None:
        pass

    def get_plugin(
        self,
        avater_name: str,
        avatar_id: str,
        memory_mode: str,
        memory_search_context: int,
        memory_recall_session: int,
        maximum_memory_items: int,
        memory_init_config: dict,
        *args,
        **kwargs,
    ) -> Mem0Memory:
        try:
            from mem0 import AsyncMemory, AsyncMemoryClient
            from mem0.configs.base import MemoryConfig

            if memory_mode == "client":
                client = AsyncMemoryClient()
            else:
                if memory_init_config:
                    config = MemoryConfig(**memory_init_config)
                    client = AsyncMemory(config=config)
                else:
                    client = AsyncMemory()
            return Mem0Memory(
                avater_name=avater_name,
                avatar_id=avatar_id,
                memory_search_context=memory_search_context,
                memory_recall_session=memory_recall_session,
                maximum_memory_items=maximum_memory_items,
                client=client,
            )
        except Exception:
            raise ImportError(
                "The 'mem0' Memory plugin is required but is not installed.\n"
                "To fix this, install the optional dependency: `pip install alphaavatar-plugins-memory[mem0]`"
            )


AvatarPlugin.register_avatar_plugin(AvatarModule.MEMORY, "mem0", MemoryMem0Plugin())
