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
from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from .avatar_info_config import AvatarInfoConfig
from .livekit_plugin_config import LiveKitPluginConfig
from .memory_plugin_config import MemoryConfig
from .persona_plugin_config import PersonaConfig


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class AvatarConfig:
    """Dataclass which contains all avatar-related configuration. This
    simplifies passing around the distinct configurations in the codebase.
    """

    avatar_info: AvatarInfoConfig = Field(default_factory=AvatarInfoConfig)
    """Avatar Information configuration."""
    livekit_plugin_config: LiveKitPluginConfig = Field(default_factory=LiveKitPluginConfig)
    """Livekit Plugins configuration."""
    memory_config: MemoryConfig = Field(default_factory=MemoryConfig)
    """Avatar Memory configuration."""
    persona_config: PersonaConfig = Field(default_factory=PersonaConfig)
    """Avatar Persona configuration."""
