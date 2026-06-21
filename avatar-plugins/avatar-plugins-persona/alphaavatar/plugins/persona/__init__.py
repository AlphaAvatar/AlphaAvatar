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

    def get_plugin(self, profiler_init_config: dict, *args, **kwargs):
        try:
            return ProfilerRuntime(**profiler_init_config)
        except Exception as e:
            raise Exception(f"Failed to initialize ProfilerRuntime: {e}") from e


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


def _configure_persona_vdb_runner(persona_vdb_type: str | None = None) -> str | None:
    """
    Configure and register Persona VDB runner after PersonaConfig sets env vars.
    """
    vdb_type = persona_vdb_type or os.getenv("PERSONA_VDB_TYPE")

    logger.info("Configuring Persona plugin with VDB type: %s", vdb_type)

    if vdb_type == "qdrant":
        from .runner import QdrantRunner

        method = QdrantRunner.INFERENCE_METHOD
        os.environ["PERSONA_INFERENCE_METHOD"] = method

        AvatarPlugin.register_inference_runner_once(QdrantRunner)
        return method

    if vdb_type == "lancedb":
        from .runner import LanceDBRunner

        method = LanceDBRunner.INFERENCE_METHOD
        os.environ["PERSONA_INFERENCE_METHOD"] = method

        AvatarPlugin.register_inference_runner_once(LanceDBRunner)
        return method

    logger.warning(
        "Unsupported PERSONA_VDB_TYPE=%r. Expected 'qdrant' or 'lancedb'.",
        vdb_type,
    )
    return None


def bootstrap_inference_runners() -> None:
    """
    Plugin-owned inference runner bootstrap.

    Called by AlphaAvatar Core from AvatarServer.run() after config/env is ready
    and before LiveKit creates the inference executor.
    """
    # Speaker runners do not depend on PERSONA_VDB_TYPE.
    AvatarPlugin.register_inference_runner_once(SpeakerAttributeRunner)
    AvatarPlugin.register_inference_runner_once(SpeakerVectorRunner)
    AvatarPlugin.register_inference_runner_once(FaceAnalysisRunner)

    # Persona profile / speaker-vector storage runner.
    _configure_persona_vdb_runner()


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


# Runner bootstrap register
AvatarPlugin.register_inference_runner_bootstrap(
    "alphaavatar.plugins.persona",
    bootstrap_inference_runners,
)
