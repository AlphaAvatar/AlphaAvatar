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
"""A vector store holds one embedding model's vectors: recorded as it is made, checked as it is
opened, a store of another model refused with everything in it kept; credentials and servers
never count as another model. Real stores: LanceDB in a directory, Qdrant in memory."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from alphaavatar.agents.utils.vdb import lancedb, qdrant
from alphaavatar.agents.utils.vdb.space import EmbeddingSpace, EmbeddingSpaceError

SETTING = "memory.vdb_config.collection_name"
SMALL = {"provider": "openai", "model": "text-embedding-3-small"}
OTHER = {"provider": "google", "model": "text-embedding-004"}  # Another model, also 4-wide here.
ROWS = [
    {"id": f"m{n}", "vector": [float(n), 1.0, 0.0, 0.0], "page_content": f"memory {n}"}
    for n in range(3)
]


class Lance:
    """A LanceDB table opened as a runner opens it: made from a seed row when missing."""

    def __init__(self, root: Path) -> None:
        self.client = lancedb.get_client(client_path=root)

    def open(self, embedding: dict, size: int = 4, name: str = "memories") -> None:
        def ensure() -> None:
            if not self.client.table_exists(name):
                seed = [{"id": "__init__", "vector": [0.0] * size, "page_content": ""}]
                self.client.create_table(name, seed).delete("id = '__init__'")

        space = EmbeddingSpace.configured(embedding, size)
        self.client.claim_space(name, space, setting=SETTING, ensure=ensure)

    def rows(self, name: str = "memories") -> list[dict]:
        table = self.client.open_table(name)
        return sorted(
            ({"id": r["id"], "vector": list(r["vector"])} for r in table.to_arrow().to_pylist()),
            key=lambda row: row["id"],
        )

    def record(self, name: str = "memories") -> dict | None:
        path = self.client.path / f"{name}.embedding.json"
        return json.loads(path.read_text()) if path.exists() else None


def test_a_store_is_reopened_by_its_model_whatever_its_credentials_or_server(
    tmp_path: Path,
) -> None:
    store = Lance(tmp_path)
    store.open(SMALL)
    store.client.open_table("memories").add(ROWS)
    assert store.record() == {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": None,
        "size": 4,
        "store": "memories",
        "setting": SETTING,
    }
    # Another key, another variable holding it, another server with the same model: the same
    # vectors, as before.
    for extra in (
        {},
        {"api_key_env": "MY_KEY"},
        {"api_key": "sk-rotated"},
        {"base_url": "https://proxy.invalid/v1"},
    ):
        store.open(SMALL | {"extra": extra})
    store.open({"provider": " OpenAI ", "model": "text-embedding-3-small "})
    assert len(store.rows()) == 3 and store.record()["model"] == "text-embedding-3-small"


@pytest.mark.parametrize(
    ("embedding", "size", "said"),
    [
        (OTHER, 4, "holds vectors of openai text-embedding-3-small (4-dimensional)"),
        (SMALL | {"extra": {"dimensions": 4}}, 4, "4 dimensions asked"),
        (SMALL, 8, "names openai text-embedding-3-small (8-dimensional)"),
    ],
    ids=["another-model-same-size", "dimensions-asked", "another-size"],
)
def test_a_store_of_another_space_is_refused_and_kept_whole(
    tmp_path: Path, embedding: dict, size: int, said: str
) -> None:
    store = Lance(tmp_path)
    store.open(SMALL)
    store.client.open_table("memories").add(ROWS)
    before, record = store.rows(), store.record()

    with pytest.raises(EmbeddingSpaceError) as refused:
        store.open(embedding, size)
    assert said in str(refused.value)
    assert f"give {SETTING} another name, a separate index" in str(refused.value)
    assert "Nothing was changed" in str(refused.value)
    # Nothing written: the vectors, the record; and the store opens with its own model again.
    assert (store.rows(), store.record()) == (before, record)
    store.open(SMALL)
    assert store.rows() == before


def test_another_model_takes_a_separate_index_beside_the_first(tmp_path: Path) -> None:
    store = Lance(tmp_path)
    store.open(SMALL)
    store.client.open_table("memories").add(ROWS)
    store.open(OTHER, name="memories_google")
    assert store.record("memories_google")["model"] == "text-embedding-004"
    assert store.rows("memories_google") == [] and len(store.rows()) == 3


def test_a_store_made_before_records_is_taken_only_as_far_as_it_can_be_told(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Empty: nothing to tell apart, recorded as configured.
    store = Lance(tmp_path)
    store.client.create_table(
        "empty", [{"id": "x", "vector": [0.0] * 4, "page_content": ""}]
    ).delete("id = 'x'")
    store.open(SMALL, name="empty")
    assert "assumed" not in store.record("empty")
    # Vectors of another size: another space for certain, refused, nothing recorded.
    store.client.create_table("old", ROWS)
    with pytest.raises(EmbeddingSpaceError, match="unrecorded embedding \\(4-dimensional\\)"):
        store.open(SMALL, size=8, name="old")
    assert store.record("old") is None and len(store.rows("old")) == 3
    # Vectors of its size: taken as configured, said to be unverified, and recorded so.
    caplog.set_level(logging.WARNING)
    store.open(SMALL, name="old")
    assert store.record("old")["assumed"] is True
    assert "cannot be verified" in caplog.text
    # From then on, as recorded.
    with pytest.raises(EmbeddingSpaceError):
        store.open(OTHER, name="old")


def test_qdrant_records_its_space_beside_the_collection_and_refuses_another() -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    client = QdrantClient(location=":memory:")

    def open(embedding: dict, size: int = 4, name: str = "memories") -> None:
        def ensure() -> None:
            if not client.collection_exists(name):
                client.create_collection(
                    name, vectors_config=VectorParams(size=size, distance=Distance.COSINE)
                )

        qdrant.claim_space(
            client, name, EmbeddingSpace.configured(embedding, size), setting=SETTING, ensure=ensure
        )

    def points(name: str = "memories") -> int:
        return client.count(name, exact=True).count

    open(SMALL)
    client.upsert(
        "memories",
        points=[
            PointStruct(id=n, vector=row["vector"], payload={"m": n}) for n, row in enumerate(ROWS)
        ],
    )
    open(SMALL | {"extra": {"api_key_env": "ROTATED"}})
    with pytest.raises(
        EmbeddingSpaceError, match="Qdrant collection 'memories' holds vectors of openai"
    ):
        open(OTHER)
    assert points() == 3
    record = client.retrieve("memories__embedding", ids=[0], with_payload=True)[0].payload
    assert (record["model"], record["size"]) == ("text-embedding-3-small", 4)
    # Made before records: its size told, refused when it differs; taken as assumed otherwise.
    client.create_collection("old", vectors_config=VectorParams(size=4, distance=Distance.COSINE))
    client.upsert("old", points=[PointStruct(id=1, vector=[1.0, 0.0, 0.0, 0.0])])
    with pytest.raises(EmbeddingSpaceError, match="4-dimensional"):
        open(SMALL, size=8, name="old")
    assert not client.collection_exists("old__embedding")
    open(SMALL, name="old")
    assert (
        client.retrieve("old__embedding", ids=[0], with_payload=True)[0].payload["assumed"] is True
    )
    assert points("old") == 1


def test_recorded_stores_are_told_from_their_records_alone(tmp_path: Path) -> None:
    from alphaavatar.agents.utils.vdb.space import recorded_conflicts

    indexes, elsewhere = tmp_path / "indexes", tmp_path / "elsewhere"
    for directory, name, setting in (
        (indexes / "memory/lancedb", "memories", "memory.vdb_config.collection_name"),
        (indexes / "persona/lancedb", "profiles", "persona.vdb_config.profiler_collection_name"),
        (elsewhere, "mcp", "tools.mcp.vdb_config.collection_name"),
    ):
        directory.mkdir(parents=True)
        record = EmbeddingSpace.configured(SMALL, 4).record(store=name, setting=setting)
        (directory / f"{name}.embedding.json").write_text(json.dumps(record))

    def settings(embedding: dict, **changes) -> dict:
        return {
            "memory": {
                "plugin": "default",
                "vdb_config": {"collection_name": "memories", "embedding": embedding},
            }
            | changes.get("memory", {}),
            "persona": {
                "plugin": "default",
                "vdb_config": {"profiler_collection_name": "profiles", "embedding": SMALL},
            },
            "tools": {
                "mcp": {
                    "plugin": "default",
                    "enabled": True,
                    "vdb_config": {
                        "collection_name": "mcp",
                        "client_path": str(elsewhere),
                        "embedding": OTHER,
                    },
                }
            },
        }

    # MCP's store, named by its own directory: another model there too.
    found = recorded_conflicts(settings(OTHER), [indexes])
    assert [line.split(" holds ")[0] for line in found] == [
        f"LanceDB table 'memories' in {indexes / 'memory/lancedb'}",
        f"LanceDB table 'mcp' in {elsewhere}",
    ]
    assert "give memory.vdb_config.collection_name another name" in found[0]
    # The same model, its key elsewhere; another store; memory off: nothing for memory.
    for embedding, changes in (
        (SMALL | {"extra": {"api_key_env": "MY_KEY"}}, {}),
        (
            OTHER,
            {"memory": {"vdb_config": {"collection_name": "memories_google", "embedding": OTHER}}},
        ),
        (OTHER, {"memory": {"plugin": None}}),
    ):
        assert [
            f
            for f in recorded_conflicts(settings(embedding, **changes), [indexes])
            if "memories" in f
        ] == []
