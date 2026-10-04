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
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .model_input import ModelInput


class ModelGenerationOptions(BaseModel):
    """Per-request generation choices; they never change the shared client's identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    temperature: float | None = Field(default=None, ge=0.0, le=2.0, allow_inf_nan=False)
    max_output_tokens: int | None = Field(default=None, gt=0)
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None


@dataclass(frozen=True, slots=True)
class ModelToolDefinition:
    """Projection of a callable capability. No handler or tool registry lives here."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    strict: bool = False


@dataclass(frozen=True, slots=True)
class ModelRequest:
    request_id: str = field(default_factory=lambda: uuid4().hex)

    input: ModelInput
    tools: tuple[ModelToolDefinition, ...] = ()

    output_schema: type[BaseModel] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    options: ModelGenerationOptions = field(default_factory=ModelGenerationOptions)
    tool_choice: Literal["auto", "none", "required"] = "auto"
    parallel_tool_calls: bool = False

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("Model request identity cannot be empty")
        if self.tool_choice not in {"auto", "none", "required"}:
            raise ValueError("Unknown tool choice")
        if self.tool_choice == "required" and not self.tools:
            raise ValueError("Required tool choice needs callable tools")
        if self.output_schema is not None and (
            not isinstance(self.output_schema, type)
            or not issubclass(self.output_schema, BaseModel)
        ):
            raise TypeError("output_schema must be a Pydantic model class")
