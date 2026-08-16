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

# Only these values are implemented. The keys exist so that the K and V axes of
# the UnifiedMem framework are explicit in configuration; adding a value later
# is an enum extension rather than a refactor. Unimplemented values raise --
# silent downgrades hide which pipeline actually ran.
IMPLEMENTED_KEY_ORGANIZATIONS = {"merge_by_value"}
IMPLEMENTED_VALUE_SOURCES = {"item"}


class NoteMode(str, Enum):
    """How the note layer is maintained on top of the atomic item layer."""

    OFF = "off"
    SESSION_SUMMARY = "session_summary"
    SESSION_MERGE = "session_merge"


class ItemOp(str, Enum):
    ADD = "add"


class CandidateSource(str, Enum):
    NOTE_LOOKUP = "note_lookup"
    QUERY_RECALL = "query_recall"
    UNION = "union"


class ExtractionConfig(BaseModel):
    session_gate: bool = Field(
        default=False,
        description="Prepend a prompt fragment telling the model to emit nothing "
        "when the session holds no durable value.",
    )
    relations: bool = Field(
        default=False,
        description="Extract semantic relations between the entities already "
        "mentioned by each memory. Not implemented yet; entities alone are "
        "extracted and become graph nodes.",
    )

    @field_validator("relations")
    @classmethod
    def _check_relations(cls, v: bool) -> bool:
        if v:
            raise ValueError(
                "extraction.relations=True is not implemented. Entities are already "
                "extracted as graph nodes; relation extraction will reuse them as "
                "endpoints. See docs/_local/specs/memory-layering--2026-08-16-design.md"
            )
        return v


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
    source: str = Field(default="item")

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str) -> str:
        if v not in IMPLEMENTED_VALUE_SOURCES:
            raise ValueError(
                f"value.source={v!r} is not implemented. "
                f"Available: {sorted(IMPLEMENTED_VALUE_SOURCES)}"
            )
        return v


class NoteConfig(BaseModel):
    mode: NoteMode = Field(default=NoteMode.SESSION_MERGE)
    resolve_covered_items: bool | None = Field(
        default=None,
        description="Let a note supply the prompt-facing value of every item it "
        "absorbed. None follows the mode default.",
    )
    max_item_ids: int = Field(default=200, ge=1)

    @property
    def enabled(self) -> bool:
        return self.mode is not NoteMode.OFF

    @property
    def resolves_covered_items(self) -> bool:
        """Whether V resolution is on.

        Defaults by mode: session_merge needs it (suppressing the superseded
        item is the whole mechanism), session_summary does not (there is no
        cross-session correction to suppress, and the summary and the atomic
        facts complement each other).
        """
        if self.resolve_covered_items is not None:
            return self.resolve_covered_items
        return self.mode is NoteMode.SESSION_MERGE


class MaintenanceConfig(BaseModel):
    item_ops: list[ItemOp] = Field(default_factory=lambda: [ItemOp.ADD])
    candidate_source: CandidateSource = Field(default=CandidateSource.NOTE_LOOKUP)
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
    key: KeyConfig = Field(default_factory=KeyConfig)
    value: ValueConfig = Field(default_factory=ValueConfig)
    note: NoteConfig = Field(default_factory=NoteConfig)
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
