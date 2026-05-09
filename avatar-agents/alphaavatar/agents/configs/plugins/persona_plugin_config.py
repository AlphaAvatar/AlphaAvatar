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
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.persona import PersonaBase
from alphaavatar.agents.utils.vdb import qdrant

if TYPE_CHECKING:
    from alphaavatar.agents.configs import SessionConfig

importlib.import_module("alphaavatar.plugins.persona")


class PersonaConfig(BaseModel):
    """Configuration for the Persona plugin used in the agent."""

    # Persona Metadata
    maximum_retrieval_times: int = Field(
        default=3,
        description="The maximum number of retrieval to determine whether a new user matches existing data in the Persona database.",
    )

    # Persona Profile plugin config
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
        description="Avatar speaker profile plugin to use for user profile extraction from user voice.",
    )
    speaker_init_config: dict = Field(
        default={},
        description="Custom configuration parameters for the speaker profile plugin.",
    )

    # Persona VDB Config
    persona_vdb_config: dict = Field(
        default={},
        description="Custom initialization parameters for the persona vdb backend (e.g., host, port, url, api_key, prefer_grpc).",
    )

    def model_post_init(self, __context):
        os.environ["PERSONA_VDB_CONFIG"] = json.dumps(self.persona_vdb_config)

        if self.profiler_plugin == "default":
            try:
                qdrant.get_client(**self.persona_vdb_config)
                persona_vdb_type = "qdrant"
            except ValueError:
                persona_vdb_type = "lancedb"

            os.environ["PERSONA_VDB_TYPE"] = persona_vdb_type

        else:
            # TODO: Handle custom profiler plugins and corresponding VDB runners.
            pass

    def get_plugin(self, session_config: "SessionConfig") -> PersonaBase:
        """Returns the Persona plugin instance based on the configuration."""
        return PersonaBase(
            profiler=AvatarPlugin.get_avatar_plugin(
                AvatarModule.PROFILER,
                self.profiler_plugin,
                user_path=session_config.user_path,
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
