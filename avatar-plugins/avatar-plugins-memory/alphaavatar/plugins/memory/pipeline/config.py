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
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

# Only these values are implemented this round. The keys exist so that the
# K and V axes of the UnifiedMem framework are explicit in configuration;
# adding a value later is an enum extension rather than a refactor.
IMPLEMENTED_KEY_ORGANIZATIONS = {"merge_by_value"}
IMPLEMENTED_VALUE_SOURCES = {"note"}


class MaintenanceOp(str, Enum):
    ADD = "add"
    NOOP = "noop"
    UPDATE = "update"


class ExtractionConfig(BaseModel):
    session_gate: bool = Field(
        default=False,
        description="Prepend a prompt fragment telling the model to emit nothing "
        "when the session holds no durable value.",
    )
    keywords: bool = Field(
        default=True,
        description="Ask the extractor for note-level keywords (the K of S/F/K).",
    )


class KeyConfig(BaseModel):
    organization: str = Field(default="merge_by_value")
    include_topic: bool = Field(default=True)

    @field_validator("organization")
    @classmethod
    def _check_organization(cls, v: str) -> str:
        if v not in IMPLEMENTED_KEY_ORGANIZATIONS:
            raise ValueError(
                f"key.organization={v!r} is not implemented. "
                f"Available: {sorted(IMPLEMENTED_KEY_ORGANIZATIONS)}"
            )
        return v


class ValueConfig(BaseModel):
    source: str = Field(default="note")

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str) -> str:
        if v not in IMPLEMENTED_VALUE_SOURCES:
            raise ValueError(
                f"value.source={v!r} is not implemented. "
                f"Available: {sorted(IMPLEMENTED_VALUE_SOURCES)}"
            )
        return v


class MaintenanceConfig(BaseModel):
    ops: list[MaintenanceOp] = Field(default_factory=lambda: [MaintenanceOp.ADD])
    similarity_threshold: float = Field(default=0.82, ge=0.0, le=1.0)
    max_candidates_per_note: int = Field(default=5, ge=1, le=50)
    timeout: float = Field(default=30.0, gt=0.0)

    @model_validator(mode="after")
    def _check_ops(self) -> "MaintenanceConfig":
        if MaintenanceOp.ADD not in self.ops:
            raise ValueError("maintenance.ops must contain 'add'")
        if MaintenanceOp.UPDATE in self.ops and MaintenanceOp.NOOP not in self.ops:
            raise ValueError("maintenance.ops with 'update' requires 'noop'")
        return self

    @property
    def uses_llm(self) -> bool:
        return MaintenanceOp.NOOP in self.ops or MaintenanceOp.UPDATE in self.ops

    @property
    def allow_update(self) -> bool:
        return MaintenanceOp.UPDATE in self.ops


class MemoryPipelineConfig(BaseModel):
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    key: KeyConfig = Field(default_factory=KeyConfig)
    value: ValueConfig = Field(default_factory=ValueConfig)
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
