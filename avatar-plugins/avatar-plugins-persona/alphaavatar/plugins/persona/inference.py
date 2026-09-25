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
import os
from collections.abc import Mapping
from typing import Any

from alphaavatar.agents.runtime.inference import InferenceRunner

from .config import DefaultPersonaConfig


def configure_inference_runners(config: Mapping[str, Any]) -> tuple[type[InferenceRunner], ...]:
    persona = config["persona"]
    if persona["plugin"] != "default":
        return ()
    options = DefaultPersonaConfig.model_validate(persona["init_config"])

    runners = []
    if options.speaker.enabled:
        from .processors.speaker.attribute_runner import SpeakerAttributeRunner
        from .processors.speaker.vector_runner import SpeakerVectorRunner

        runners.extend((SpeakerAttributeRunner, SpeakerVectorRunner))

    if options.face.enabled:
        from .processors.face.analysis_runner import FaceAnalysisRunner

        runners.append(FaceAnalysisRunner)

    backend = os.getenv("PERSONA_VDB_TYPE")
    if backend == "qdrant":
        from .storage.vdb import QdrantRunner as runner
    elif backend == "lancedb":
        from .storage.vdb import LanceDBRunner as runner
    else:
        raise ValueError(f"Unsupported PERSONA_VDB_TYPE: {backend!r}")

    os.environ["PERSONA_VDB_INFERENCE_METHOD"] = runner.INFERENCE_METHOD

    runners.append(runner)
    return tuple(runners)
