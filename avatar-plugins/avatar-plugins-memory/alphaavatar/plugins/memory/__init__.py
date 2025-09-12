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
from .mem0_client import Mem0ClientMemory
from .version import __version__

__all__ = [
    "__version__",
]


class MemoryMem0ClientPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self) -> None:
        pass

    def get_plugin(
        self,
        avater_name: str,
        avatar_id: str,
        memory_search_context: int,
        memory_recall_session: int,
        maximum_memory_items: int,
        memory_init_config: dict,
        *args,
        **kwargs,
    ) -> Mem0ClientMemory:
        try:
            return Mem0ClientMemory(
                avater_name=avater_name,
                avatar_id=avatar_id,
                memory_search_context=memory_search_context,
                memory_recall_session=memory_recall_session,
                maximum_memory_items=maximum_memory_items,
                memory_init_config=memory_init_config,
            )
        except Exception:
            raise ImportError(
                "The 'mem0_client' Memory plugin is required but is not installed.\n"
                "To fix this, install the optional dependency: `pip install alphaavatar-plugins-memory[mem0]`"
            )


AvatarPlugin.register_avatar_plugin(AvatarModule.MEMORY, "mem0_client", MemoryMem0ClientPlugin())
