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
from .plugins.character_config import VirtualCharacterConfig
from .plugins.llm_config import LLMConfig
from .plugins.memory_config import MemoryConfig
from .plugins.persona_config import PersonaConfig
from .plugins.router_config import RouterConfig
from .plugins.status_config import StatusConfig
from .plugins.tools_config import ToolsConfig
from .plugins.vision_config import VisionConfig
from .plugins.voice_config import VoiceConfig


class AvatarConfig(BaseModel):
    """
    Top-level Avatar configuration.

    Contains runtime settings and all configurable Avatar plugins.
    """

    avatar: AvatarInfoConfig = Field(default_factory=AvatarInfoConfig)
    """Avatar information configuration."""

    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    """Runtime configuration, which will creat for each session."""

    status: StatusConfig = Field(default_factory=StatusConfig)
    """Intermediate status plugin configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    """LLM plugin configuration."""

    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    """Voice plugin configuration."""

    vision: VisionConfig = Field(default_factory=VisionConfig)
    """Vision plugin configuration."""

    router: RouterConfig = Field(default_factory=RouterConfig)
    """Interaction Router plugin configuration."""

    character: VirtualCharacterConfig = Field(default_factory=VirtualCharacterConfig)
    """Virtual character plugin configuration."""

    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    """Memory plugin configuration."""

    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    """Persona plugin configuration."""

    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    """Tool plugin configuration."""
