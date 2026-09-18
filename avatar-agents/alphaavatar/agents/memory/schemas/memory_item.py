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
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from alphaavatar.agents.utils.time import application_now

from ..enums import MemoryKind, MemoryScopeKind, MemoryType
from .context import MemoryContextRef
from .graph import MemoryGraphLink, MemoryGraphNode
from .reference import MemoryOwnerRef, MemoryParticipantRef, MemorySourceRef
from .scope import MemoryScope


def _deduplicate_refs(values):
    out, seen = [], set()
    for value in values:
        if value.key not in seen:
            seen.add(value.key)
            out.append(value)
    return out


def _deduplicate_ids(values) -> list[str]:
    values = [values] if isinstance(values, str) else values or []
    out, seen = [], set()
    for value in values:
        value = str(value).strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


class MemoryItem(BaseModel):
    """
    atomic
        source_memory_ids = []
        supersedes_memory_ids = []

    consolidated summary
        source_memory_ids = [...]
        supersedes_memory_ids = []

    consolidated merge/correction
        source_memory_ids = [...]
        supersedes_memory_ids = [...]
    """

    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: MemoryKind = MemoryKind.ATOMIC

    context: MemoryContextRef
    scope: MemoryScope = Field(default_factory=MemoryScope.owner)

    owner_refs: list[MemoryOwnerRef]
    participant_refs: list[MemoryParticipantRef] = Field(default_factory=list)
    source_refs: list[MemorySourceRef] = Field(default_factory=list)

    value: str
    topic: str | None = None

    created_at: datetime = Field(default_factory=application_now)
    updated_at: datetime | None = None
    revision: int = Field(default=1, ge=1)
    memory_type: MemoryType

    source_memory_ids: list[str] = Field(default_factory=list)
    supersedes_memory_ids: list[str] = Field(default_factory=list)

    graph_nodes: list[MemoryGraphNode] = Field(default_factory=list)
    graph_links: list[MemoryGraphLink] = Field(default_factory=list)

    extra_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("owner_refs", mode="after")
    @classmethod
    def _normalize_owners(cls, value):
        value = _deduplicate_refs(value)
        if not value:
            raise ValueError("owner_refs cannot be empty")
        return value

    @field_validator("participant_refs", "source_refs", mode="after")
    @classmethod
    def _normalize_refs(cls, value):
        return _deduplicate_refs(value)

    @field_validator("source_memory_ids", "supersedes_memory_ids", mode="before")
    @classmethod
    def _normalize_memory_ids(cls, value):
        return _deduplicate_ids(value)

    @model_validator(mode="after")
    def _validate_relations(self) -> "MemoryItem":
        self.updated_at = self.updated_at or self.created_at

        if (
            self.scope.kind is MemoryScopeKind.CONVERSATION
            and self.scope.scope_id != self.context.conversation_id
        ):
            raise ValueError("conversation scope_id must match context.conversation_id")

        if (
            self.scope.kind is MemoryScopeKind.CONTEXT
            and self.scope.scope_id != self.context.context_id
        ):
            raise ValueError("context scope_id must match context.context_id")

        if self.memory_id in self.source_memory_ids or self.memory_id in self.supersedes_memory_ids:
            raise ValueError("memory cannot reference itself")

        if not set(self.supersedes_memory_ids).issubset(self.source_memory_ids):
            raise ValueError("supersedes_memory_ids must be a subset of source_memory_ids")

        if self.kind is MemoryKind.ATOMIC and (
            self.source_memory_ids or self.supersedes_memory_ids
        ):
            raise ValueError("atomic memories cannot reference source memories")

        if self.kind is MemoryKind.CONSOLIDATED and not self.source_memory_ids:
            raise ValueError("consolidated memories require source_memory_ids")

        return self

    def render_line(self) -> str:
        parts = [f"Created At: {self.created_at.isoformat()}"]
        if self.topic:
            parts.append(f"Topic: {self.topic}")
        parts.append(f"Content: {self.value}")
        return "; ".join(parts)

    def embedding_text(self, *, include_topic: bool = False) -> str:
        return f"{self.topic}\n{self.value}" if include_topic and self.topic else self.value
