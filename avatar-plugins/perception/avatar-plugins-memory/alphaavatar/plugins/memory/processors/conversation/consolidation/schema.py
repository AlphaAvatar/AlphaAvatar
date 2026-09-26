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
from dataclasses import dataclass

from pydantic import BaseModel, Field

from alphaavatar.agents.memory.schemas import MemoryItem

NEW_CONSOLIDATED_PREFIX = "new:"


class MemoryAssignment(BaseModel):
    source_memory_id: str = Field(description="Incoming atomic memory id.")

    target_memory_id: str = Field(
        description=("Existing consolidated memory id or 'new:<k>' for a new consolidated memory.")
    )

    reason: str = Field(
        default="",
        description="Short explanation for the assignment.",
    )


class ConsolidatedMemoryDraft(BaseModel):
    memory_id: str = Field(description="Existing consolidated memory id or 'new:<k>'.")

    value: str = Field(
        default="",
        description=("Updated consolidated memory content in natural prose."),
    )


class ConsolidationPlan(BaseModel):
    assignments: list[MemoryAssignment] = Field(default_factory=list)
    memories: list[ConsolidatedMemoryDraft] = Field(default_factory=list)


@dataclass(slots=True)
class ConsolidationResult:
    source_items: list[MemoryItem]
    to_insert: list[MemoryItem]
    to_rewrite: list[MemoryItem]

    def all_writes(self) -> list[MemoryItem]:
        return [
            *self.source_items,
            *self.to_insert,
            *self.to_rewrite,
        ]
