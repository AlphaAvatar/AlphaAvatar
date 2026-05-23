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
from typing import Literal

from livekit.agents import llm
from pydantic import BaseModel, Field


class LLMPluginConfig(BaseModel):
    """Configuration for the LLM plugin used in the agent."""

    llm_plugin: Literal["openai"] | None = Field(
        default=None,
        description="LLM plugin to use for language/real-time model interactions.",
    )
    llm_model: str | None = Field(
        default=None,
        description="Model to use for language/real-time model interactions.",
    )

    def model_post_init(self, __context): ...

    def get_plugin(self) -> llm.LLM | llm.RealtimeModel | None:
        """Returns the LLM plugin based on llm config."""

        if self.llm_model is None:
            return None

        match self.llm_plugin:
            case "openai":
                try:
                    from livekit.plugins import openai
                except ImportError:
                    raise ImportError(
                        "The 'openai.LLM' plugin is required for livekit.plugins.openai but is not installed.\n"
                        "To fix this, install the optional dependency: `pip install livekit-plugins-openai`"
                    )
                return openai.LLM(model=self.llm_model)
            case _:
                return None
