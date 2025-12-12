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

from .avatar_info_config import AvatarInfoConfig
from .plugins.character_plugin_config import VirtualCharacterConfig
from .plugins.livekit_plugin_config import LiveKitPluginConfig
from .plugins.memory_plugin_config import MemoryConfig
from .plugins.persona_plugin_config import PersonaConfig
from .plugins.tools_plugin_config import ToolsConfig


class AvatarConfig(BaseModel):
    """Dataclass which contains all avatar-related configuration. This
    simplifies passing around the distinct configurations in the codebase.
    """

    livekit_plugin_config: LiveKitPluginConfig = Field(default_factory=LiveKitPluginConfig)
    """Livekit Plugins configuration."""

    avatar_info: AvatarInfoConfig = Field(default_factory=AvatarInfoConfig)
    """Avatar Information configuration."""
    character_config: VirtualCharacterConfig = Field(default_factory=VirtualCharacterConfig)
    """Avatar Virtual Character configuration."""
    memory_config: MemoryConfig = Field(default_factory=MemoryConfig)
    """Avatar Memory configuration."""
    persona_config: PersonaConfig = Field(default_factory=PersonaConfig)
    """Avatar Persona configuration."""

    tools_config: ToolsConfig = Field(default_factory=ToolsConfig)
    """Avatar Tools configuration."""
