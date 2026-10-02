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
from typing import Any

from pydantic import BaseModel

from .model_input import ModelInput


@dataclass(frozen=True, slots=True)
class ModelToolDefinition:
    """Model-facing projection of a callable capability, not another tool registry."""

    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ModelRequest:
    input: ModelInput
    tools: tuple[ModelToolDefinition, ...] = ()
    output_schema: type[BaseModel] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
