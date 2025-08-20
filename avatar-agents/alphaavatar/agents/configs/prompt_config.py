from typing import Any, Optional, Literal
from pydantic.dataclasses import dataclass
from pydantic import Field, ConfigDict


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class PromptConfig:
    """Configuration for the prompt used in the agent."""
    
    avatar_introduction: str = Field(
        default="You are a helpful voice AI assistant.",
        description="Introduction of the avatar.",
    )
