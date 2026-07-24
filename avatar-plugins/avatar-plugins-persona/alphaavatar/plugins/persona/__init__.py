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
from .profiler_runtime import ProfilerRuntime
from .runner import FaceAnalysisRunner, SpeakerAttributeRunner, SpeakerVectorRunner
from .version import __version__

__all__ = [
    "__version__",
]


class ProfilerPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(
        self,
        *,
        runtime: AvatarRuntime,
        profiler_init_config: dict,
        **kwargs,
    ):
        try:
            return ProfilerRuntime(
                runtime=runtime,
                **profiler_init_config,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize ProfilerRuntime: {e}") from e


class SpeakerPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self):
        from .models import SPEAKER_MODEL_CONFIG, download_from_hf_hub

        for model_name in SPEAKER_MODEL_CONFIG.keys():
            download_from_hf_hub(
                SPEAKER_MODEL_CONFIG[model_name].hf_model,
                SPEAKER_MODEL_CONFIG[model_name].file_name,
                revision=SPEAKER_MODEL_CONFIG[model_name].revision,
            )

    def get_plugin(self, speaker_init_config: dict, *args, **kwargs):
        from .speaker_cache import SpeakerCache
        from .speaker_stream import SpeakerStreamWrapper

        return (SpeakerStreamWrapper, SpeakerCache)


class FacePlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self):
        # InsightFace downloads buffalo_l by default during initialization.
        # This can be changed to explicitly pre-download it to INSIGHTFACE_ROOT.
        pass

    def get_plugin(self, face_init_config: dict | None = None, *args, **kwargs):
        from .face_cache import FaceCache
        from .face_stream import FaceStreamWrapper

        return (FaceStreamWrapper, FaceCache)


def configure_vdb_runner(vdb_type: str | None = None) -> None:
    vdb_type = vdb_type or os.getenv("PERSONA_VDB_TYPE")

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
            "Unsupported PERSONA_VDB_TYPE=%r. Expected 'qdrant' or 'lancedb'.",
            vdb_type,
        )
        return None

    os.environ["PERSONA_VDB_INFERENCE_METHOD"] = method
    return None


# Plugin register
AvatarPlugin.register_avatar_plugin(
    AvatarModule.PROFILER,
    "default",
    ProfilerPlugin(),
)

AvatarPlugin.register_avatar_plugin(
    AvatarModule.SPEAKER,
    "default",
    SpeakerPlugin(),
)

AvatarPlugin.register_avatar_plugin(
    AvatarModule.FACE,
    "default",
    FacePlugin(),
)


# Inference Runners
InferenceRunner.register(SpeakerAttributeRunner)
InferenceRunner.register(SpeakerVectorRunner)
InferenceRunner.register(FaceAnalysisRunner)
AvatarPlugin.register_inference_runner_bootstrap(
    "alphaavatar.plugins.persona.vdb",
    configure_vdb_runner,
)
