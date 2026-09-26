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
from __future__ import annotations

from typing import Any

from alphaavatar.agents.memory.schemas import MemoryItem


def serialize_memory_items(
    records: list[MemoryItem],
    *,
    include_topic: bool = True,
) -> list[dict[str, Any]]:
    return [
        {
            "id": memory.memory_id,
            "doc_kind": "memory_item",
            "page_content": memory.value,
            "embedding_text": memory.embedding_text(include_topic=include_topic),
            "metadata": {
                "memory_kind": memory.kind.value,
                "episode_id": memory.context.episode_id,
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
