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
from pydantic import BaseModel, Field

from alphaavatar.agents.configs.runtime_config import RuntimeConfig

from .avatar_info_config import AvatarInfoConfig
from .plugins.foundation import ContextConfig, LLMConfig, LoopConfig, VisionConfig, VoiceConfig
from .plugins.perception import (
    MemoryConfig,
    PersonaConfig,
    RouterConfig,
    StatusConfig,
    VirtualCharacterConfig,
)
from .plugins.tools import ToolsConfig


class AvatarConfig(BaseModel):
    """Runtime settings and configurable Avatar plugins."""

    # Avatar information
    avatar: AvatarInfoConfig = Field(default_factory=AvatarInfoConfig)

    # Runtime configuration
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

    # Foundation plugins configuration
    context: ContextConfig = Field(default_factory=ContextConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)

    # Avatar plugins configuration
    status: StatusConfig = Field(default_factory=StatusConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    character: VirtualCharacterConfig = Field(default_factory=VirtualCharacterConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)

    # Tools configuration
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
