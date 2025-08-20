from typing import Any, Optional, Literal
from pydantic.dataclasses import dataclass
from pydantic import Field, ConfigDict

from .plugin_config import LiveKitPluginConfig
from .prompt_config import PromptConfig


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class AvatarConfig:
    """Dataclass which contains all avatar-related configuration. This
    simplifies passing around the distinct configurations in the codebase.
    """

    livekit_plugin_config: LiveKitPluginConfig = Field(default_factory=LiveKitPluginConfig)
    """Livekit Plugins configuration."""
    prompt_config: PromptConfig = Field(default_factory=PromptConfig)
    """Prompts configuration."""
