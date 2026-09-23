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

import os

from alphaavatar.agents.runtime.inference import (
    InferenceRunner,
    register_inference_runner_bootstrap,
)
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin

from .factory import PersonaPlugin
from .log import logger
from .processors import FaceAnalysisRunner, SpeakerAttributeRunner, SpeakerVectorRunner
from .version import __version__

__all__ = ["__version__"]


def configure_vdb_runner(vdb_type: str | None = None) -> None:
    vdb_type = vdb_type or os.getenv("PERSONA_VDB_TYPE")
    logger.info("Configuring Persona plugin with VDB type: %s", vdb_type)

    if vdb_type == "qdrant":
        from .storage.vdb import QdrantRunner

        method = QdrantRunner.INFERENCE_METHOD
        InferenceRunner.register(QdrantRunner)

    elif vdb_type == "lancedb":
        from .storage.vdb import LanceDBRunner

        method = LanceDBRunner.INFERENCE_METHOD
        InferenceRunner.register(LanceDBRunner)

    else:
        logger.warning(
            "Unsupported PERSONA_VDB_TYPE=%r. Expected 'qdrant' or 'lancedb'.",
            vdb_type,
        )
        return

    os.environ["PERSONA_VDB_INFERENCE_METHOD"] = method


# Plugin register
AvatarModulePlugin.register(
    AvatarModule.PERSONA,
    "default",
    PersonaPlugin(),
)

# Inference Runners
InferenceRunner.register(SpeakerAttributeRunner)
InferenceRunner.register(SpeakerVectorRunner)
InferenceRunner.register(FaceAnalysisRunner)

register_inference_runner_bootstrap(
    "alphaavatar.plugins.persona.vdb",
    configure_vdb_runner,
)
