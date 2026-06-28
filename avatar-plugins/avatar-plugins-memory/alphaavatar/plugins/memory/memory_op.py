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
from typing import Any

from pydantic import BaseModel, Field

from alphaavatar.agents.memory import MemoryItem
from alphaavatar.agents.memory.schema.graph import (
    GraphNodeMention,
    MemoryGraphLink,
    MemoryGraphNode,
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
        description="A list of memory contents where the Assistant interacts with the user based on the conversation content.",
    )
    assistant_memory_entries: list[PatchOp] = Field(
        default_factory=list,
        description="The Assistant's own memory list is generated based on the conversation content and the memory content list of the Assistant's interaction with the user.",
    )


def norm_token(s: Any) -> str:
    """Normalize for case/whitespace-insensitive equality."""
    return " ".join(str(s).strip().lower().split())


def flatten_items(memory_items: list[MemoryItem]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for memory in memory_items:
        items.append(
            {
                "id": memory.memory_id,
                "page_content": memory.value,
                "metadata": {
                    "session_id": memory.session_id,
                    "object_ids": memory.object_ids,
                    "topic": memory.topic,
                    "ts": memory.timestamp,
                    "memory_type": (
                        memory.memory_type.value
                        if hasattr(memory.memory_type, "value")
                        else str(memory.memory_type)
                    ),
                    "graph_nodes": [x.model_dump(mode="json") for x in memory.graph_nodes],
                    "graph_links": [x.model_dump(mode="json") for x in memory.graph_links],
                    "extra_data": memory.extra_data,
                },
            }
        )

    return items


def rebuild_from_items(items: list[dict[str, Any]]) -> list[MemoryItem]:
    out: list[MemoryItem] = []

    for it in items:
        mid = it.get("id", None)
        value = it.get("page_content", None)
        meta = it.get("metadata", {}) or {}

        if mid is None or value is None:
            continue

        out.append(
            MemoryItem(
                memory_id=mid,
                value=value,
                session_id=meta.get("session_id"),
                object_ids=meta.get("object_ids") or [],
                topic=meta.get("topic"),
                timestamp=meta.get("ts"),
                memory_type=meta.get("memory_type"),
                graph_nodes=[
                    MemoryGraphNode.model_validate(x) for x in meta.get("graph_nodes") or []
                ],
                graph_links=[
                    MemoryGraphLink.model_validate(x) for x in meta.get("graph_links") or []
                ],
                extra_data=meta.get("extra_data") or {},
            )
        )

    return out
