# Copyright 2025 AlphaAvatar project
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
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from alphaavatar.agents.utils.time import application_now

from ..enum.memory_type import MemoryType
from .graph import MemoryGraphLink, MemoryGraphNode


class MemoryItem(BaseModel):
    updated: bool = Field(default=False)

    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str

    # all related runtime owners or participants
    # object_ids: Avatar id / user id / tool id / env source id
    object_ids: list[str] = Field(default_factory=list)

    value: str
    topic: str | None = None

    created_at: datetime = Field(default_factory=application_now)

    memory_type: MemoryType

    graph_nodes: list[MemoryGraphNode] = Field(default_factory=list)
    graph_links: list[MemoryGraphLink] = Field(default_factory=list)

    extra_data: dict[str, Any] = Field(default_factory=dict)

    def render_line(self) -> str:
        """Single-line prompt-facing rendering (the V side)."""
        parts = [f"Created At: {self.created_at.isoformat()}"]
        if self.topic:
            parts.append(f"Topic: {self.topic}")
        parts.append(f"Content: {self.value}")
        return "; ".join(parts).strip()

    def embedding_text(self, *, include_topic: bool = False) -> str:
        """Text handed to the embedder (the K side)."""
        if include_topic and self.topic:
            return f"{self.topic}\n{self.value}"
        return self.value


class MemoryNote(MemoryItem):
    """Aggregation layer over immutable atomic MemoryItems.

    Adds nothing but the coverage set: `value` carries the consolidated
    narrative, and the atomic statements it consolidates stay in the item
    layer, addressed here by `item_ids`.

    `session_id` means "the session in which this note was last updated", not
    a boundary -- a note may span any number of sessions. `created_at` keeps
    the time the event was first observed and is never overwritten by an
    update.

    Updating a note must produce a NEW object; the project forbids in-place
    mutation of memory records.
    """

    item_ids: list[str] = Field(default_factory=list)
