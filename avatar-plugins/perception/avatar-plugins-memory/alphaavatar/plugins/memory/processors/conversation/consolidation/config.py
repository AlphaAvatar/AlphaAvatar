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
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class ConsolidationMode(StrEnum):
    OFF = "off"
    SESSION_SUMMARY = "session_summary"
    SESSION_MERGE = "session_merge"


class ItemOp(StrEnum):
    ADD = "add"


class CandidateSource(StrEnum):
    CONSOLIDATED_LOOKUP = "consolidated_lookup"
    QUERY_RECALL = "query_recall"
    UNION = "union"


class ExtractionConfig(BaseModel):
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


class ConsolidationConfig(BaseModel):
    mode: ConsolidationMode = ConsolidationMode.SESSION_MERGE

    resolve_superseded_items: bool | None = Field(
        default=None,
        description=(
            "Replace superseded atomic memories with their consolidated memory "
            "at prompt resolution time. None follows the mode default."
        ),
    )

    @property
    def enabled(self) -> bool:
        return self.mode is not ConsolidationMode.OFF

    @property
    def resolves_superseded_items(self) -> bool:
        if self.resolve_superseded_items is not None:
            return self.resolve_superseded_items

        return self.mode is ConsolidationMode.SESSION_MERGE


class MaintenanceConfig(BaseModel):
    item_ops: list[ItemOp] = Field(default_factory=lambda: [ItemOp.ADD])

    candidate_source: CandidateSource = CandidateSource.CONSOLIDATED_LOOKUP

    similarity_threshold: float = Field(default=0.82, ge=0.0, le=1.0)
    max_candidates_per_item: int = Field(default=5, ge=1, le=50)
    timeout: float = Field(default=30.0, gt=0.0)

    @model_validator(mode="after")
    def _check_item_ops(self) -> "MaintenanceConfig":
        if ItemOp.ADD not in self.item_ops:
            raise ValueError("maintenance.item_ops must contain 'add'")

        return self


class MemoryPipelineConfig(BaseModel):
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    consolidation: ConsolidationConfig = Field(default_factory=ConsolidationConfig)
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
