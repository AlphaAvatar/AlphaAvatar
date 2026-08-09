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
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..enum.memory_type import MemoryType
from .graph import MemoryGraphLink, MemoryGraphNode


class MemoryItem(BaseModel):
    updated: bool = Field(default=False)

    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str

    # all related runtime owners or participants
    object_ids: list[str] = Field(
        default_factory=list
    )  # Avatar id / user id / tool id / env source id

    value: str
    topic: str | None = None
    timestamp: str

    memory_type: MemoryType

    graph_nodes: list[MemoryGraphNode] = Field(default_factory=list)
    graph_links: list[MemoryGraphLink] = Field(default_factory=list)

    extra_data: dict[str, Any] = Field(default_factory=dict)

    def render_line(self) -> str:
        """Single-line prompt-facing rendering (the V side)."""
        parts = [f"Timestamp: {self.timestamp}"]
        if self.topic:
            parts.append(f"Topic: {self.topic}")
        parts.append(f"Content: {self.value}")
        return "; ".join(parts).strip()

    def embedding_text(self, *, include_topic: bool = False) -> str:
        """Text handed to the embedder (the K side)."""
        if include_topic and self.topic:
            return f"{self.topic}\n{self.value}"
        return self.value


def render_note_value(summary: str, facts: list[str]) -> str:
    """Compose the human-readable value of a note from its summary and facts."""
    parts: list[str] = []
    if summary:
        parts.append(summary)
    parts.extend(fact for fact in facts if fact)
    return "\n".join(parts)


class MemoryNote(MemoryItem):
    """Session-level aggregation of dialog memory. Only for MemoryType.CONVERSATION.

    `value` is composed from summary + facts at construction time and is therefore
    optional. Updating a note must produce a new object (the project forbids
    in-place mutation); otherwise `value` would go stale.
    """

    value: str = ""

    summary: str = ""
    facts: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _compose_value(self) -> "MemoryNote":
        if not self.value:
            self.value = render_note_value(self.summary, self.facts)
        return self

    def render_line(self) -> str:
        parts = [f"Timestamp: {self.timestamp}"]
        if self.topic:
            parts.append(f"Topic: {self.topic}")
        parts.append(f"Summary: {self.summary}")
        if self.facts:
            parts.append("Details: " + " | ".join(self.facts))
        return "; ".join(parts).strip()

    def embedding_text(self, *, include_topic: bool = False) -> str:
        parts: list[str] = []
        if include_topic and self.topic:
            parts.append(self.topic)
        if self.summary:
            parts.append(self.summary)
        parts.extend(fact for fact in self.facts if fact)
        if self.keywords:
            parts.append(" ".join(self.keywords))
        return "\n".join(parts)
