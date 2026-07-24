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
import os

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.inference import InferenceRunner

from .log import logger
from .memory_runtime import MemoryRuntime
from .version import __version__

__all__ = [
    "__version__",
]


class MemoryPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(
        self,
        runtime: AvatarRuntime,
        avatar_id: str,
        memory_search_context: int,
        memory_recall_num: int,
        maximum_memory_num: int,
        memory_init_config: dict,
        *args,
        **kwargs,
    ) -> MemoryRuntime:
        try:
            return MemoryRuntime(
                runtime=runtime,
                avatar_id=avatar_id,
                memory_search_context=memory_search_context,
                memory_recall_num=memory_recall_num,
                maximum_memory_num=maximum_memory_num,
                **memory_init_config,
            )
        except Exception as e:
            raise ImportError(f"Failed to initialize MemoryRuntime plugin: {e}") from e


def configure_vdb_runner(vdb_type: str | None = None) -> None:
    vdb_type = vdb_type or os.getenv("MEMORY_VDB_TYPE")

    logger.info("Configuring Persona plugin with VDB type: %s", vdb_type)

    if vdb_type == "qdrant":
        from .runner import QdrantRunner

        method = QdrantRunner.INFERENCE_METHOD
        InferenceRunner.register(QdrantRunner)

    elif vdb_type == "lancedb":
        from .runner import LanceDBRunner

        method = LanceDBRunner.INFERENCE_METHOD
        InferenceRunner.register(LanceDBRunner)

    else:
        logger.warning(
            "Unsupported MEMORY_VDB_TYPE=%r. Expected 'qdrant' or 'lancedb'.",
            vdb_type,
        )
        return None

    os.environ["MEMORY_VDB_INFERENCE_METHOD"] = method
    return None


# Plugin register
AvatarPlugin.register_avatar_plugin(
    AvatarModule.MEMORY,
    "default",
    MemoryPlugin(),
)

# Inference Runners
AvatarPlugin.register_inference_runner_bootstrap(
    "alphaavatar.plugins.memory.vdb",
    configure_vdb_runner,
)
