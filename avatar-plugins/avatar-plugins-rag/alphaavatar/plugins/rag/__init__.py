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
from alphaavatar.agents.runtime import SessionRuntime
from alphaavatar.agents.tools import RAGAPI

from .log import logger
from .rag_anything import RAGAnythingTool
from .version import __version__

__all__ = [
    "__version__",
]


class RAGAnythingPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(
        self,
        session_runtime: SessionRuntime,
        rag_init_config: dict,
        *args,
        **kwargs,
    ) -> RAGAPI:
        try:
            status_emitter = kwargs.pop("status_emitter", None)

            rag_obj = RAGAnythingTool(
                session_path=session_runtime.session_path, **rag_init_config, **kwargs
            )
        except (ImportError, ModuleNotFoundError) as e:
            raise ImportError(
                "The 'raganything[default]' RAG plugin is required but is not installed.\n"
                "Install it via: `pip install alphaavatar-plugins-rag`"
            ) from e

        return RAGAPI(rag_object=rag_obj, status_emitter=status_emitter)


# plugin init
AvatarPlugin.register_avatar_plugin(AvatarModule.RAG, "default", RAGAnythingPlugin())
