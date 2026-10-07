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

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaavatar.agents.avatar.provider.schemas import ModelInput


class LoopLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_model_steps: int = Field(default=6, ge=1, le=64)
    max_tool_rounds: int = Field(default=4, ge=0, le=64)
    max_tool_calls: int = Field(default=12, ge=0, le=256)
    max_parallel_tools: int = Field(default=3, ge=1, le=32)
    total_timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    finalization_reserve: float = Field(default=12.0, gt=0, allow_inf_nan=False)
    tool_timeout: float = Field(default=15.0, gt=0, allow_inf_nan=False)
    max_same_call: int = Field(default=1, ge=1, le=8)
    max_no_progress_steps: int = Field(default=2, ge=1, le=8)
    max_arguments_bytes: int = Field(default=65_536, ge=1)
    max_result_bytes: int = Field(default=262_144, ge=1)
    max_output_tokens: int = Field(default=4096, ge=16)
    final_output_tokens: int = Field(default=1536, ge=16)

    @model_validator(mode="after")
    def validate_reserve(self) -> LoopLimits:
        if self.finalization_reserve >= self.total_timeout:
            raise ValueError("Finalization reserve must be smaller than the total timeout")
        return self


@dataclass(frozen=True, slots=True)
class LoopRequest:
    input_id: str
    turn_id: str
    context_id: str

    input: ModelInput

    allowed_capabilities: tuple[str, ...] = ()
    limits: LoopLimits = field(default_factory=LoopLimits)
    depth: Literal["auto", "quick", "careful"] = "auto"

    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (self.turn_id, self.context_id, self.input_id)
        ):
            raise ValueError("Loop requests require turn_id, context_id and input_id")
        if self.depth not in {"auto", "quick", "careful"}:
            raise ValueError("Unknown execution depth")
        if len(set(self.allowed_capabilities)) != len(self.allowed_capabilities):
            raise ValueError("Allowed capability identities must be unique")
        if len({item.id for item in self.input.items}) != len(self.input.items):
            raise ValueError("Loop input contains duplicate item identities")
