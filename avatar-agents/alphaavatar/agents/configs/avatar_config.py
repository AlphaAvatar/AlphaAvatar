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
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaavatar.agents.configs.runtime_config import RuntimeConfig

from .avatar_info_config import AvatarInfoConfig
from .plugins.foundation import ContextConfig, LoopConfig, VisionConfig, VoiceConfig
from .plugins.perception import (
    MemoryConfig,
    PersonaConfig,
    RouterConfig,
    StatusConfig,
    VirtualCharacterConfig,
)
from .plugins.tools import ToolsConfig


class AvatarConfig(BaseModel):
    """Runtime settings and configurable Avatar plugins, not SDK generation settings."""

    model_config = ConfigDict(extra="forbid")

    # Avatar information and runtime configuration.
    avatar: AvatarInfoConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

    # Foundation plugins.
    context: ContextConfig = Field(default_factory=ContextConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)

    # Agent-owned plugins.
    status: StatusConfig = Field(default_factory=StatusConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    character: VirtualCharacterConfig = Field(default_factory=VirtualCharacterConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @model_validator(mode="before")
    @classmethod
    def validate_sections(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        if "llm" in value:
            raise ValueError("llm was removed; configure loop.init_config.model instead")
        if "defaults" not in value:
            return value
        if not isinstance(value["defaults"], Mapping):
            raise ValueError("defaults must be a mapping of YAML anchor definitions")
        # YAML aliases are already expanded. This is authoring data, not a runtime section.
        return {key: item for key, item in value.items() if key != "defaults"}
