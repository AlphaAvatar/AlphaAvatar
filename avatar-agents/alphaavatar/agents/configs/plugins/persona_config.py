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
import importlib
import json
import os
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.persona import PersonaBase
from alphaavatar.agents.utils.vdb import qdrant

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import SessionRuntime


importlib.import_module("alphaavatar.plugins.persona")


class PersonaPluginConfig(BaseModel):
    """Common plugin config for persona submodules."""

    model_config = ConfigDict(extra="forbid")

    plugin: str = Field(
        default="default",
        description="Persona sub-plugin name.",
    )
    init_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Custom initialization parameters for this persona sub-plugin.",
    )


class PersonaConfig(BaseModel):
    """Configuration for the Persona plugin used in the agent."""

    model_config = ConfigDict(extra="forbid")

    maximum_retrieval_times: int = Field(
        default=3,
        description=(
            "The maximum number of retrieval attempts used to determine whether "
            "a new user matches existing persona data."
        ),
    )

    profiler: PersonaPluginConfig = Field(default_factory=PersonaPluginConfig)
    speaker: PersonaPluginConfig = Field(default_factory=PersonaPluginConfig)
    face: PersonaPluginConfig = Field(default_factory=PersonaPluginConfig)

    vdb_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Custom initialization parameters for the persona VDB backend "
            "(e.g. host, port, url, api_key, prefer_grpc, embedding)."
        ),
    )

    def model_post_init(self, __context):
        os.environ["PERSONA_VDB_CONFIG"] = json.dumps(self.vdb_config)

        if self.profiler.plugin == "default":
            try:
                qdrant.get_client(**self.vdb_config)
                persona_vdb_type = "qdrant"
            except ValueError:
                persona_vdb_type = "lancedb"

            os.environ["PERSONA_VDB_TYPE"] = persona_vdb_type

    def get_plugin(self, session_runtime: "SessionRuntime") -> PersonaBase:
        """Returns the Persona plugin instance based on the configuration."""
        return PersonaBase(
            session_runtime=session_runtime,
            profiler=AvatarPlugin.get_avatar_plugin(
                AvatarModule.PROFILER,
                self.profiler.plugin,
                profiler_init_config=self.profiler.init_config,
            ),
            speaker_cls=AvatarPlugin.get_avatar_plugin(
                AvatarModule.SPEAKER,
                self.speaker.plugin,
                speaker_init_config=self.speaker.init_config,
            ),
            face_cls=AvatarPlugin.get_avatar_plugin(
                AvatarModule.FACE,
                self.face.plugin,
                face_init_config=self.face.init_config,
            ),
            maximum_retrieval_times=self.maximum_retrieval_times,
        )
