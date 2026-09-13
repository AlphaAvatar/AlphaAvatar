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

import importlib
import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.persona import PersonaBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.utils.vdb import qdrant

importlib.import_module("alphaavatar.plugins.persona")


class PersonaProcessorConfig(BaseModel):
    """Configuration for a Persona component factory."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Whether this Persona processor is enabled.",
    )
    plugin: str = Field(default="default", description="Persona component plugin name.")
    init_config: dict[str, Any] = Field(
        default_factory=dict, description="Component initialization parameters."
    )


class PersonaConfig(BaseModel):
    """Configuration for the Persona runtime plugin."""

    model_config = ConfigDict(extra="forbid")

    plugin: str = Field(default="default", description="Persona runtime plugin name.")
    vdb_config: dict[str, Any] = Field(
        default_factory=dict, description="Persona VDB initialization parameters."
    )

    profiler: PersonaProcessorConfig = Field(default_factory=PersonaProcessorConfig)
    speaker: PersonaProcessorConfig = Field(default_factory=PersonaProcessorConfig)
    face: PersonaProcessorConfig = Field(default_factory=PersonaProcessorConfig)

    def model_post_init(self, __context: Any) -> None:
        os.environ["PERSONA_VDB_CONFIG"] = json.dumps(self.vdb_config)

        if self.plugin != "default":
            return

        try:
            qdrant.get_client(**self.vdb_config)
            vdb_type = "qdrant"
        except ValueError:
            vdb_type = "lancedb"

        os.environ["PERSONA_VDB_TYPE"] = vdb_type

    def get_plugin(self, runtime: AvatarRuntime) -> PersonaBase:
        persona = AvatarPlugin.get_avatar_plugin(
            AvatarModule.PERSONA,
            self.plugin,
            runtime=runtime,
            init_config=self.model_dump(
                exclude={
                    "plugin",
                    "vdb_config",
                }
            ),
        )
        if persona is None:
            raise ValueError(f"Persona plugin '{self.plugin}' is not registered or returned None.")
        if not isinstance(persona, PersonaBase):
            raise TypeError(
                f"Persona plugin '{self.plugin}' must return PersonaBase, got {type(persona).__name__}."
            )
        return persona
