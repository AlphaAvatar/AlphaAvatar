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
from alphaavatar.agents.runtime.plugin import AvatarModule

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

    # The outer model renders nested errors: plugin sections may carry credentials.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

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

    def plugin_packages(self) -> dict[str, str]:
        """The built-in plugins the selections use, by configuration location.

        Plugin ``<name>`` is the module ``alphaavatar.plugins.<name>``, installed by the package
        ``alpha-avatar-plugins-<name>``. Validation imports none of them: building a section
        imports its plugin, and runner planning imports them all, since each registers its
        factories and inference runners on import.
        """
        voice, tools = self.voice, self.tools
        selected = {
            "context.plugin": ("context", self.context.plugin == "default"),
            "loop.plugin": ("loop", self.loop.plugin == "realtime"),
            **{
                f"voice.{part}.plugin": ("voice", getattr(voice, part).plugin is not None)
                for part in ("vad", "stt", "tts")
            },
            # Always built, whichever plugin they name; status even while its events are off.
            "status.plugin": ("status", True),
            "character.plugin": ("character", self.character.plugin is not None),
            "memory.plugin": ("memory", True),
            "persona.plugin": ("persona", True),
            "router.plugin": ("router", True),
            "tools.deepresearch.plugin": ("deepresearch", tools.deepresearch.plugin is not None),
            "tools.rag.plugin": ("rag", tools.rag.plugin is not None),
            "tools.mcp.enabled": ("mcp", tools.mcp.enabled and tools.mcp.plugin is not None),
        }
        return {location: name for location, (name, used) in selected.items() if used}

    def plugin_factories(self) -> dict[str, tuple[AvatarModule, str]]:
        """The module factory each selection creates at start, by configuration location.

        Loop and context plugins register theirs when their entry point loads; the others when
        their package is imported.
        """
        voice, tools = self.voice, self.tools
        selected = {
            "loop.plugin": (AvatarModule.LOOP, self.loop.plugin),
            "context.plugin": (AvatarModule.CONTEXT, self.context.plugin),
            "voice.vad.plugin": (AvatarModule.VOICE_VAD, voice.vad.plugin),
            "voice.stt.plugin": (AvatarModule.VOICE_STT, voice.stt.plugin),
            "voice.tts.plugin": (AvatarModule.VOICE_TTS, voice.tts.plugin),
            "status.plugin": (AvatarModule.STATUS, self.status.plugin),
            "router.plugin": (AvatarModule.ROUTER, self.router.plugin),
            "character.plugin": (AvatarModule.CHARACTER, self.character.plugin),
            "memory.plugin": (AvatarModule.MEMORY, self.memory.plugin),
            "persona.plugin": (AvatarModule.PERSONA, self.persona.plugin),
            "tools.deepresearch.plugin": (AvatarModule.DEEPRESEARCH, tools.deepresearch.plugin),
            "tools.rag.plugin": (AvatarModule.RAG, tools.rag.plugin),
            "tools.mcp.plugin": (AvatarModule.MCP, tools.mcp.plugin if tools.mcp.enabled else None),
        }
        return {location: factory for location, factory in selected.items() if factory[1]}

    def section(self, location: str) -> BaseModel:
        """The section a setting belongs to: ``tools.mcp`` for ``tools.mcp.enabled``."""
        section: BaseModel = self
        for part in location.split(".")[:-1]:
            section = getattr(section, part)
        return section
