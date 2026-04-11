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

from livekit.agents.inference_runner import _InferenceRunner

from alphaavatar.agents import AvatarModule, AvatarPlugin

from .log import logger
from .profiler_langchain import ProfilerLangChain
from .runner import SpeakerAttributeRunner, SpeakerVectorRunner
from .version import __version__

__all__ = [
    "__version__",
]


class ProfilerLangchainPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(self, profiler_init_config: dict, *args, **kwargs):
        try:
            return ProfilerLangChain(**profiler_init_config)
        except Exception:
            raise ImportError(
                "The 'langchain[default]' Profiler plugin is required but is not installed.\n"
                "To fix this, install the optional dependency: `pip install alphaavatar-plugins-persona`"
            )


class SpeakerPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self):
        from .models import MODEL_CONFIG, download_from_hf_hub

        for model_name in MODEL_CONFIG.keys():
            download_from_hf_hub(
                MODEL_CONFIG[model_name].hf_model,
                MODEL_CONFIG[model_name].file_name,
                revision=MODEL_CONFIG[model_name].revision,
            )

    def get_plugin(self, speaker_init_config: dict, *args, **kwargs):
        from .speaker_cache import SpeakerCache
        from .speaker_stream import SpeakerStreamWrapper

        return (SpeakerStreamWrapper, SpeakerCache)


# plugin init
AvatarPlugin.register_avatar_plugin(AvatarModule.PROFILER, "default", ProfilerLangchainPlugin())
AvatarPlugin.register_avatar_plugin(AvatarModule.SPEAKER, "default", SpeakerPlugin())


# SpeakerRunner register
_InferenceRunner.register_runner(SpeakerAttributeRunner)
_InferenceRunner.register_runner(SpeakerVectorRunner)

# VDBRunner register
persona_vdb_type = os.getenv("PERSONA_VDB_TYPE", None)
match persona_vdb_type:
    case "qdrant":
        from . import profiler_langchain, speaker_stream
        from .runner import QdrantRunner

        profiler_langchain.PROFILER_INFERENCE_METHOD = QdrantRunner.INFERENCE_METHOD
        speaker_stream.SPEAKER_INFERENCE_METHOD = QdrantRunner.INFERENCE_METHOD
        _InferenceRunner.register_runner(QdrantRunner)

    case "lancedb":
        from . import profiler_langchain, speaker_stream
        from .runner import LanceDBRunner

        profiler_langchain.PROFILER_INFERENCE_METHOD = LanceDBRunner.INFERENCE_METHOD
        speaker_stream.SPEAKER_INFERENCE_METHOD = LanceDBRunner.INFERENCE_METHOD
        _InferenceRunner.register_runner(LanceDBRunner)
