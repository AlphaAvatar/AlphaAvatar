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
from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents.providers import ProvidersConfig

from .consolidation import MemoryPipelineConfig


class ConversationProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = "memory.conversation_delta"
    gateway: ProvidersConfig = Field(default_factory=ProvidersConfig)


class ConversationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    provider: ConversationProviderConfig = Field(default_factory=ConversationProviderConfig)
    pipeline: MemoryPipelineConfig = Field(default_factory=MemoryPipelineConfig)
