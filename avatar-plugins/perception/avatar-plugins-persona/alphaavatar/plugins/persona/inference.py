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
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.utils.vdb.config import vdb_backend

from .config import DefaultPersonaConfig

if TYPE_CHECKING:
    from alphaavatar.agents.configs.avatar_config import AvatarConfig


def get_vdb_runner(config: dict[str, Any]) -> type[InferenceRunner]:
    backend = vdb_backend(config)
    if backend == "qdrant":
        from .storage.vdb.qdrant import QdrantRunner as runner
    elif backend == "lancedb":
        from .storage.vdb.lancedb import LanceDBRunner as runner
    else:
        raise ValueError(f"Unsupported vector backend: {backend!r}")
    return runner


def configure_inference_runners(config: AvatarConfig) -> tuple[type[InferenceRunner], ...]:
    persona = config.persona
    if persona.plugin != "default":
        return ()
    options = DefaultPersonaConfig.model_validate(persona.init_config)

    runners: list[type[InferenceRunner]] = []
    if options.speaker.enabled:
        from .processors.speaker.attribute_runner import SpeakerAttributeRunner
        from .processors.speaker.vector_runner import SpeakerVectorRunner

        runners.extend((SpeakerAttributeRunner, SpeakerVectorRunner))

    if options.face.enabled:
        from .processors.face.analysis_runner import FaceAnalysisRunner

        runners.append(FaceAnalysisRunner)

    runners.append(get_vdb_runner(persona.vdb_config))
    return tuple(runners)
