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
from livekit.agents.inference_runner import _InferenceRunner

from alphaavatar.agents import AvatarModule, AvatarPlugin

from .log import logger
from .memory_langchain import MemoryLangchain
from .runner import QdrantRunner
from .version import __version__

__all__ = [
    "__version__",
]


class MemoryLangchainPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(
        self,
        memory_search_context: int,
        memory_recall_num: int,
        maximum_memory_num: int,
        memory_init_config: dict,
        *args,
        **kwargs,
    ) -> MemoryLangchain:
        try:
            return MemoryLangchain(
                memory_search_context=memory_search_context,
                memory_recall_num=memory_recall_num,
                maximum_memory_num=maximum_memory_num,
                memory_init_config=memory_init_config,
            )
        except Exception:
            raise ImportError(
                "The 'langchain[default]' Memory plugin is required but is not installed.\n"
                "To fix this, install the optional dependency: `pip install alphaavatar-plugins-memory`"
            )


# plugin init
AvatarPlugin.register_avatar_plugin(AvatarModule.MEMORY, "default", MemoryLangchainPlugin())

# runner init
_InferenceRunner.register_runner(QdrantRunner)
