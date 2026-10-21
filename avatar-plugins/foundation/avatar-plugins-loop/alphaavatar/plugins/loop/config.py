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
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaavatar.agents.avatar.loop.schemas.request import QueryDifficulty
from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig, ProviderTraceConfig
from alphaavatar.agents.avatar.provider.schemas.request import ReasoningEffort


class ToolPolicy(BaseModel):
    """Deployment policy for capabilities already granted to the Run, not model authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    read_only: bool = False
    parallel_safe: bool = False
    approval_required: bool = False


class ReasoningConfig(BaseModel):
    """Declared model support and query selection are separate deployment decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_effort: ReasoningEffort | None = "none"
    supported_efforts: tuple[ReasoningEffort, ...] = ("none",)
    difficulty_efforts: dict[QueryDifficulty, ReasoningEffort] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_profile(self) -> ReasoningConfig:
        supported = self.supported_efforts
        if len(supported) > 16 or len(set(supported)) != len(supported):
            raise ValueError("Reasoning support must contain distinct bounded effort names")
        if any(not value or len(value) > 32 or value != value.strip() for value in supported):
            raise ValueError("Reasoning effort names must be trimmed and contain 1..32 characters")
        selected = (*self.difficulty_efforts.values(), self.default_effort)
        if any(value is not None and value not in supported for value in selected):
            raise ValueError("Reasoning policy selects an effort not declared by the model profile")
        return self

    def resolve(self, *, difficulty: QueryDifficulty | None, effort: str | None) -> str | None:
        if effort is None:
            if difficulty is not None:
                if difficulty not in self.difficulty_efforts:
                    raise ValueError(f"No reasoning policy for query difficulty {difficulty!r}")
                effort = self.difficulty_efforts[difficulty]
            else:
                effort = self.default_effort
        if effort is not None and effort not in self.supported_efforts:
            raise ValueError(f"Reasoning effort {effort!r} is not supported by the model profile")
        return effort


class RealtimeLoopConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # model configuration
    model: ProviderTaskConfig
    trace: ProviderTraceConfig = Field(default_factory=ProviderTraceConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)

    # policy configuration
    tool_policies: dict[str, ToolPolicy] = Field(default_factory=dict)
    feedback_timeout: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    max_retiring_runs: int = Field(default=4, ge=0, le=32)
