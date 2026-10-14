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

from pydantic import BaseModel, Field, model_validator


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


class ConsolidationConfig(BaseModel):
    mode: ConsolidationMode = ConsolidationMode.SESSION_MERGE

    resolve_superseded_items: bool | None = Field(
        default=None,
        description=(
            "Replace superseded atomic memories with their consolidated memory "
            "at prompt resolution time. None follows the mode default."
        ),
    )
    item_ops: list[ItemOp] = Field(default_factory=lambda: [ItemOp.ADD])
    candidate_source: CandidateSource = CandidateSource.CONSOLIDATED_LOOKUP
    similarity_threshold: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum cosine similarity between an atomic memory and a consolidated "
            "memory for the latter to become a candidate. Depends on the embedding "
            "model: related memories of one user measured 0.49-0.59."
        ),
    )
    max_candidates_per_item: int = Field(default=5, ge=1, le=50)
    timeout: float = Field(default=30.0, gt=0.0)

    @model_validator(mode="after")
    def _check_item_ops(self) -> "ConsolidationConfig":
        if ItemOp.ADD not in self.item_ops:
            raise ValueError("maintenance.item_ops must contain 'add'")

        return self

    @property
    def enabled(self) -> bool:
        return self.mode is not ConsolidationMode.OFF

    @property
    def resolves_superseded_items(self) -> bool:
        if self.resolve_superseded_items is not None:
            return self.resolve_superseded_items

        return self.mode is ConsolidationMode.SESSION_MERGE
