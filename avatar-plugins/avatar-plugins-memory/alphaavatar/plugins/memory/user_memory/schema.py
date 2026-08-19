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
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from alphaavatar.agents.memory import MemoryItem, MemoryNote

# Prefix the model uses to declare a note it is creating rather than updating.
NEW_NOTE_PREFIX = "new:"

# ------------------------- LLM consolidation output -------------------------
# Judgement and rewriting are one call: an item's assignment and the resulting
# note text are the same decision.


class NoteAssignment(BaseModel):
    item_id: str = Field(description="Id of the incoming atomic memory.")
    note_id: str = Field(
        description=(
            "Id of the existing note this memory belongs to, or 'new:<k>' to put "
            "it in a new note numbered k."
        )
    )
    reason: str = Field(
        default="",
        description=(
            "One sentence on why this memory belongs there rather than anywhere "
            "else. Names the evidence that decided it."
        ),
    )


class NoteDraft(BaseModel):
    note_id: str = Field(description="Existing note id, or 'new:<k>'.")
    value: str = Field(
        default="",
        description=(
            "The consolidated narrative for this note, rewritten to include the "
            "newly assigned memories. Plain prose, no structured labels."
        ),
    )


class NoteConsolidation(BaseModel):
    assignments: list[NoteAssignment] = Field(default_factory=list)
    notes: list[NoteDraft] = Field(default_factory=list)


# ------------------------- Consolidation outcome -------------------------


@dataclass
class ConsolidationResult:
    """Outcome of the note consolidation stage.

    items      -- the session's atomic memories, re-created carrying the
                  `_note_id` back-reference of whichever note absorbed them.
                  The item layer is append-only: nothing here is ever dropped.
    to_insert  -- newly created notes
    to_rewrite -- existing notes whose content was merged/updated. These KEEP
                  their original memory_id so the VDB save (delete-by-id +
                  reinsert) behaves as an upsert.
    """

    items: list[MemoryItem] = field(default_factory=list)
    to_insert: list[MemoryNote] = field(default_factory=list)
    to_rewrite: list[MemoryNote] = field(default_factory=list)

    def all_writes(self) -> list[MemoryItem]:
        return [*self.items, *self.to_insert, *self.to_rewrite]
