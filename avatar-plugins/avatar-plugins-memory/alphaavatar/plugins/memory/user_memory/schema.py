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
"""Structured output of the note consolidation call.

Judgement and rewriting are one call, not two: an item's assignment and the
resulting note text are the same decision, and splitting them costs a round
trip while letting the two halves disagree.
"""

from pydantic import BaseModel, Field

# Prefix the model uses to declare a note it is creating rather than updating.
NEW_NOTE_PREFIX = "new:"


class NoteAssignment(BaseModel):
    item_id: str = Field(description="Id of the incoming atomic memory.")
    note_id: str = Field(
        description=(
            "Id of the existing note this memory belongs to, or 'new:<k>' to put "
            "it in a new note numbered k."
        )
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
    topic: str | None = Field(default=None, description="Stable short topic label.")


class NoteConsolidation(BaseModel):
    assignments: list[NoteAssignment] = Field(default_factory=list)
    notes: list[NoteDraft] = Field(default_factory=list)
