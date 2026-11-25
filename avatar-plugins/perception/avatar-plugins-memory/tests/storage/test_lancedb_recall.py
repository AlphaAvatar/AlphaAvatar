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
"""A recall embeds its query only when what its readers read holds a memory: each memory type
through its kind of owner, whatever the scope."""

from __future__ import annotations

from pathlib import Path

from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.utils.vdb import lancedb
from alphaavatar.plugins.memory.storage.vdb.lancedb_runner import LanceDBRunner

DIMENSION = 4


class CountingEmbeddings:
    """A remote embedding model stand-in: each query it embeds is counted."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [1.0, 0.0, 0.0, 0.0]


def runner(path: Path) -> tuple[LanceDBRunner, CountingEmbeddings]:
    # The runner as initialize() leaves it, without a launch or a remote model.
    found = LanceDBRunner.__new__(LanceDBRunner)
    found._client = lancedb.get_client(client_path=path)
    found._ensure_collection("memories", DIMENSION)
    found._memory_table = found._client.open_table("memories")
    found._embeddings = CountingEmbeddings()
    return found, found._embeddings


def memory(memory_id: str, owner: str, scope: str, memory_type: MemoryType) -> dict:
    row = dict.fromkeys(
        (
            "id",
            "page_content",
            "doc_kind",
            "memory_id",
            "memory_kind",
            "memory_type",
            "episode_id",
            "context_id",
            "runtime_session_id",
            "parent_context_id",
            "task_id",
            "scope_key",
            "topic",
            "created_at",
            "updated_at",
            "node_id",
            "node_key",
            "node_type",
        ),
        "",
    )
    json_lists = ("owner_refs_json", "participant_refs_json", "source_refs_json")
    return (
        row
        | dict.fromkeys(json_lists, "[]")
        | {
            "id": memory_id,
            "vector": [1.0, 0.0, 0.0, 0.0],
            "page_content": "likes green",
            "doc_kind": "memory_item",
            "memory_id": memory_id,
            "memory_type": memory_type.value,
            "scope_key": scope,
            "owner_keys": [owner],
            "revision": 1,
            "source_memory_ids_json": "[]",
            "supersedes_memory_ids_json": "[]",
            "node_weight": 0.0,
            "graph_nodes_json": "[]",
            "graph_links_json": "[]",
            "extra_data_json": "{}",
        }
    )


def test_a_recall_with_nothing_to_find_embeds_no_query(tmp_path: Path) -> None:
    """An empty store, or one holding only memories its readers do not read, returns no
    candidates without embedding: someone else's, and a user memory the Avatar also owns. The
    reader's own are embedded for and found, in any scope."""
    store, embeddings = runner(tmp_path / "lancedb")
    user, avatar = [MemoryType.CONVERSATION.value, MemoryType.ENV.value], [MemoryType.Avatar.value]
    readers = [
        {"memory_types": avatar, "owner_keys": ["avatar:a"]},
        {"memory_types": user, "owner_keys": ["user:a"]},
    ]
    search = {"context_str": "### user:\nWhat color?", "visibility": readers, "top_k": 3}

    assert store._search_by_context(**search)["candidates"] == []
    store._memory_table.add(
        [
            memory("m-b", "user:b", "context:a", MemoryType.CONVERSATION),
            memory("m-env", "avatar:a", "context:a", MemoryType.ENV),
        ]
    )
    assert store._search_by_context(**search)["candidates"] == []
    assert store._search_by_context(**search | {"visibility": []})["candidates"] == []
    assert embeddings.queries == []

    store._memory_table.add(
        [
            memory("m-a", "user:a", "context:another", MemoryType.CONVERSATION),
            memory("m-avatar", "avatar:a", "owner:*", MemoryType.Avatar),
        ]
    )
    found = store._search_by_context(**search)
    assert sorted(c["memory_id"] for c in found["candidates"]) == ["m-a", "m-avatar"]
    assert embeddings.queries == ["### user:\nWhat color?"]
