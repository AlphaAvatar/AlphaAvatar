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


class SemanticAddressingModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "qwen3_0_6b_q8_0"


class SemanticAddressingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    avatar_identities: tuple[str, ...] = ("AlphaAvatar",)
    history_turns: int = Field(default=2, ge=0)
    model: SemanticAddressingModelConfig = Field(default_factory=SemanticAddressingModelConfig)

    @field_validator("avatar_identities")
    @classmethod
    def validate_avatar_identities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not values:
            raise ValueError("Semantic addressing requires at least one Avatar identity")
        return values
