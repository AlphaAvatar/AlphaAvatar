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
from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaavatar.agents.avatar.provider.schemas import ProvidersConfig

from .consolidation import ConsolidationConfig


class ConversationProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = "memory.conversation_delta"
    gateway: ProvidersConfig = Field(default_factory=ProvidersConfig)


class ExtractionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_gate: bool = Field(
        default=False,
        description=(
            "Tell the model to emit nothing when the current input contains "
            "no durable memory value."
        ),
    )

    relations: bool = Field(
        default=False,
        description=(
            "Extract semantic relations between entities already mentioned by "
            "a memory. Not implemented yet."
        ),
    )

    @field_validator("relations")
    @classmethod
    def _check_relations(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "extraction.relations=True is not implemented. "
                "Entity mentions already become graph nodes."
            )

        return value


class ConversationPipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    consolidation: ConsolidationConfig = Field(default_factory=ConsolidationConfig)


class ConversationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    provider: ConversationProviderConfig = Field(default_factory=ConversationProviderConfig)
    pipeline: ConversationPipelineConfig = Field(default_factory=ConversationPipelineConfig)
