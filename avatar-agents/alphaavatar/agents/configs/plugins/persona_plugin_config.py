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

from pydantic import BaseModel, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.persona import PersonaBase

importlib.import_module("alphaavatar.plugins.persona")


class PersonaConfig(BaseModel):
    """Configuration for the Persona plugin used in the agent."""

    # Persona Metadata
    maximum_retrieval_times: int = Field(
        default=3,
        description="The maximum number of retrieval to determine whether a new user matches existing data in the Perona database.",
    )

    # Persona Profiler plugin config
    profiler_plugin: str = Field(
        default="default",
        description="Avatar profiler plugin to use for user profile extraction from chat context.",
    )
    profiler_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the profiler plugin.",
    )

    # Persona Speaker plugin config
    speaker_plugin: str = Field(
        default="default",
        description="Avatar spkear profile plugin to use for user profile extraction from user voice.",
    )
    speaker_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the spkear profile plugin.",
    )

    # Persona VDB Config
    persona_vdb_config: dict = Field(
        default={},
        description="Custom initialization parameters for the persona vdb backend (e.g., host, port, url, api_key, prefer_grpc).",
    )

    def model_post_init(self, __context):
        # Set PERONA_PROFILER_ENV
        os.environ["PERONA_VDB_CONFIG"] = json.dumps(self.persona_vdb_config)

    def get_plugin(self) -> PersonaBase:
        """Returns the Persona plugin instance based on the configuration."""
        return PersonaBase(
            profiler=AvatarPlugin.get_avatar_plugin(
                AvatarModule.PROFILER,
                self.profiler_plugin,
                profiler_init_config=self.profiler_init_config,
            ),
            speaker_cls=AvatarPlugin.get_avatar_plugin(
                AvatarModule.SPEAKER,
                self.speaker_plugin,
                speaker_init_config=self.speaker_init_config,
            ),
            face_cls=None,  # type: ignore
            maximum_retrieval_times=self.maximum_retrieval_times,
        )
