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
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from alphaavatar.agents.memory.enums import MemoryKind
from alphaavatar.agents.memory.schemas import (
    GraphNodeMention,
    MemoryContextRef,
    MemoryGraphLink,
    MemoryGraphNode,
    MemoryItem,
    MemoryOwnerRef,
    MemoryParticipantRef,
    MemoryScope,
    MemorySourceRef,
)


class PatchOp(BaseModel):
    value: str = Field(
        default="",
        description=(
            "Clean human-readable memory text. Do not include structured fields "
            "such as kind/topic/type/who/evidence/metadata."
        ),
    )
    topic: str | None = Field(
        default=None,
        description="Stable short topic label for retrieval and grouping.",
    )
    node_mentions: list[GraphNodeMention] = Field(
        default_factory=list,
        description=(
            "Lightweight graph anchors mentioned in this memory. "
            "Do not include embeddings, graph_nodes, graph_links, aliases, or evidence."
        ),
    )


class MemoryDelta(BaseModel):
    user_or_tool_memory_entries: list[PatchOp] = Field(
        default_factory=list,
        description="Memories learned from the user's conversation or tool interaction.",
    )
    assistant_memory_entries: list[PatchOp] = Field(
        default_factory=list,
        description="Memories owned by the assistant.",
    )


class EnvMemoryDelta(BaseModel):
    env_memory_entries: list[PatchOp] = Field(
        default_factory=list,
        description="Memories extracted from environmental observations.",
    )


def norm_token(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def norm_topic(value: str | None) -> str | None:
    if not value:
        return None
    value = " ".join(value.strip().split())
    return value.lower()[:64]


DOC_KIND_MEMORY = "memory_item"

LAYER_ATOMIC = MemoryKind.ATOMIC.value
LAYER_CONSOLIDATED = MemoryKind.CONSOLIDATED.value


def flatten_records(
    records: list[MemoryItem],
    *,
    include_topic: bool = False,
) -> list[dict[str, Any]]:
    return [
        {
            "id": memory.memory_id,
            "doc_kind": DOC_KIND_MEMORY,
            "page_content": memory.value,
            "embedding_text": memory.embedding_text(include_topic=include_topic),
            "metadata": {
                "memory_kind": memory.kind.value,
                "conversation_id": memory.context.conversation_id,
                "context_id": memory.context.context_id,
                "runtime_session_id": memory.context.session_id,
                "parent_context_id": memory.context.parent_context_id,
                "task_id": memory.context.task_id,
                "scope_key": memory.scope.key,
                "owner_keys": [ref.key for ref in memory.owner_refs],
                "owner_refs": [ref.model_dump(mode="json") for ref in memory.owner_refs],
                "participant_refs": [
                    ref.model_dump(mode="json") for ref in memory.participant_refs
                ],
                "source_refs": [ref.model_dump(mode="json") for ref in memory.source_refs],
                "topic": memory.topic,
                "created_at": memory.created_at.isoformat(),
                "updated_at": (memory.updated_at or memory.created_at).isoformat(),
                "revision": memory.revision,
                "memory_type": memory.memory_type.value,
                "source_memory_ids": list(memory.source_memory_ids),
                "supersedes_memory_ids": list(memory.supersedes_memory_ids),
                "graph_nodes": [node.model_dump(mode="json") for node in memory.graph_nodes],
                "graph_links": [link.model_dump(mode="json") for link in memory.graph_links],
                "extra_data": dict(memory.extra_data),
            },
        }
        for memory in records
    ]


def rebuild_from_items(
    items: list[dict[str, Any]],
) -> list[MemoryItem]:
    return [_rebuild_item(item) for item in items]


def _rebuild_item(
    item: dict[str, Any],
) -> MemoryItem:
    metadata = item["metadata"]

    return MemoryItem(
        memory_id=str(item["id"]),
        kind=MemoryKind(metadata["memory_kind"]),
        context=MemoryContextRef(
            conversation_id=str(metadata["conversation_id"]),
            context_id=str(metadata["context_id"]),
            session_id=str(metadata["runtime_session_id"]),
            parent_context_id=metadata.get("parent_context_id"),
            task_id=metadata.get("task_id"),
        ),
        scope=MemoryScope.from_key(str(metadata["scope_key"])),
        owner_refs=[MemoryOwnerRef.model_validate(ref) for ref in metadata["owner_refs"]],
        participant_refs=[
            MemoryParticipantRef.model_validate(ref)
            for ref in metadata.get("participant_refs") or []
        ],
        source_refs=[
            MemorySourceRef.model_validate(ref) for ref in metadata.get("source_refs") or []
        ],
        value=str(item["page_content"]),
        topic=metadata.get("topic"),
        created_at=metadata["created_at"],
        updated_at=metadata["updated_at"],
        revision=int(metadata["revision"]),
        memory_type=metadata["memory_type"],
        source_memory_ids=list(metadata.get("source_memory_ids") or []),
        supersedes_memory_ids=list(metadata.get("supersedes_memory_ids") or []),
        graph_nodes=[
            MemoryGraphNode.model_validate(node) for node in metadata.get("graph_nodes") or []
        ],
        graph_links=[
            MemoryGraphLink.model_validate(link) for link in metadata.get("graph_links") or []
        ],
        extra_data=dict(metadata.get("extra_data") or {}),
    )
