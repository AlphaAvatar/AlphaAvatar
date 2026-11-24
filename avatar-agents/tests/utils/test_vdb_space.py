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
import os
import threading
import uuid
from pathlib import Path

import pytest

from alphaavatar.agents.utils.vdb import lancedb, qdrant
from alphaavatar.agents.utils.vdb.space import EmbeddingSpace, EmbeddingSpaceError

SETTING = "memory.vdb_config.collection_name"
# The module each plugin's entry point names, as a build's catalog records them.
MODULES = {
    "memory": {"default": "alphaavatar.plugins.memory.factory"},
    "persona": {"default": "alphaavatar.plugins.persona.factory"},
    "tools.mcp": {"default": "alphaavatar.plugins.mcp"},
}
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
        "alphaavatar.embedding_space": 1,
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
    (record,) = [p.payload for p in client.scroll("memories__embedding", with_payload=True)[0]]
    assert (record["model"], record["size"]) == ("text-embedding-3-small", 4)
    # Made before records: its size told, refused when it differs; taken as assumed otherwise.
    client.create_collection("old", vectors_config=VectorParams(size=4, distance=Distance.COSINE))
    client.upsert("old", points=[PointStruct(id=1, vector=[1.0, 0.0, 0.0, 0.0])])
    with pytest.raises(EmbeddingSpaceError, match="4-dimensional"):
        open(SMALL, size=8, name="old")
    assert not client.collection_exists("old__embedding")
    open(SMALL, name="old")
    (record,) = [p.payload for p in client.scroll("old__embedding", with_payload=True)[0]]
    assert record["assumed"] is True
    assert points("old") == 1


def test_recorded_stores_are_told_from_their_records_alone(tmp_path: Path) -> None:
    from alphaavatar.agents.utils.vdb.space import recorded_conflicts
    from alphaavatar.agents.workspace import WorkspacePaths

    workspace, elsewhere = WorkspacePaths.from_root(tmp_path / "avatar"), tmp_path / "elsewhere"
    indexes = workspace.data.indexes
    memory = indexes.namespace("memory").backend("lancedb").root
    for directory, name, setting in (
        (memory, "memories", "memory.vdb_config.collection_name"),
        (
            indexes.namespace("persona").backend("lancedb").root,
            "profiles",
            "persona.vdb_config.profiler_collection_name",
        ),
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
                "vdb_config": {"profiler_collection_name": "profiles", "embedding": embedding},
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

    # Persona's in its own namespace's directory; MCP's named by its own: another model too.
    found = recorded_conflicts(settings(OTHER), workspace, MODULES)
    assert [line.split(" holds ")[0] for line in found] == [
        f"LanceDB table 'memories' in {memory}",
        f"LanceDB table 'profiles' in {indexes.namespace('persona').backend('lancedb').root}",
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
            for f in recorded_conflicts(settings(embedding, **changes), workspace, MODULES)
            if "memories" in f
        ] == []


"""Review of 2026-11-24: what a store and its record may never be made to do"""


class Interleaved:
    """A client as two Hosts share one: the real client, each thread held at a barrier at each
    of ``points``, (method, argument, which call, after it), so both have got that far before
    either goes on: after a call, both have seen the same; before one, both did all before it."""

    def __init__(
        self, client, barrier: threading.Barrier, *points: tuple[str, str, int, bool]
    ) -> None:
        self._client, self._barrier, self._points = client, barrier, points
        self._calls = threading.local()

    def __getattr__(self, name: str):
        found = getattr(self._client, name)
        if name not in {point[0] for point in self._points}:
            return found

        def held(*args, **kwargs):
            given = (*map(str, args), *map(str, kwargs.values()))
            at = [point for point in self._points if point[0] == name and point[1] in given]
            if not at:
                return found(*args, **kwargs)
            counts = self._calls.__dict__.setdefault("counts", {})
            counts[at[0][1]] = calls = counts.get(at[0][1], 0) + 1
            hold = [point for point in at if point[2] == calls]
            for _ in [point for point in hold if not point[3]]:
                self._barrier.wait(timeout=20)
            result = found(*args, **kwargs)
            for _ in [point for point in hold if point[3]]:
                self._barrier.wait(timeout=20)
            return result

        return held


def race(*claims) -> list[BaseException | None]:
    """Each claim in a thread of its own: what each ended with, None for success."""
    ended: list[BaseException | None] = [None] * len(claims)

    def run(index: int) -> None:
        try:
            claims[index]()
        except BaseException as error:
            ended[index] = error

    threads = [threading.Thread(target=run, args=(index,)) for index in range(len(claims))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return ended


def qdrant_open(client, embedding: dict, size: int = 4, name: str = "memories") -> None:
    from qdrant_client.models import Distance, VectorParams

    def ensure() -> None:
        if not client.collection_exists(name):
            params = VectorParams(size=size, distance=Distance.COSINE)
            client.create_collection(name, vectors_config=params)

    space = EmbeddingSpace.configured(embedding, size)
    qdrant.claim_space(client, name, space, setting=SETTING, ensure=ensure)


def test_a_collection_named_as_a_record_but_not_ones_own_is_refused_and_left_whole() -> None:
    """A collection of the record's name, holding a person's data: never taken for a record,
    written to or beside; the store is not made either."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    client = QdrantClient(location=":memory:")
    params = VectorParams(size=1, distance=Distance.DOT)
    client.create_collection("memories__embedding", vectors_config=params)
    client.upsert(
        "memories__embedding", points=[PointStruct(id=0, vector=[1.0], payload={"mine": "data"})]
    )
    with pytest.raises(EmbeddingSpaceError, match="'memories__embedding' .*not a record"):
        qdrant_open(client, SMALL)
    (point,) = client.retrieve("memories__embedding", ids=[0], with_payload=True, with_vectors=True)
    assert (point.payload, point.vector) == ({"mine": "data"}, [1.0])
    assert client.count("memories__embedding", exact=True).count == 1
    assert not client.collection_exists("memories")


@pytest.mark.parametrize("backend", ["lancedb", "qdrant"])
def test_a_store_made_before_records_is_refused_another_size_even_empty(
    backend: str, tmp_path: Path
) -> None:
    """Empty, a store still has its vectors' size: another is refused before anything is
    recorded, and the store opens as it was made."""
    if backend == "lancedb":
        store = Lance(tmp_path)
        store.client.create_table(
            "memories", [{"id": "x", "vector": [0.0] * 4, "page_content": ""}]
        ).delete("id = 'x'")

        def open(size: int) -> None:
            store.open(SMALL, size)

        def held() -> tuple:
            field = store.client.open_table("memories").schema.field("vector")
            return field.type.list_size, store.record()
    else:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        client = QdrantClient(location=":memory:")
        client.create_collection(
            "memories", vectors_config=VectorParams(size=4, distance=Distance.COSINE)
        )

        def open(size: int) -> None:
            qdrant_open(client, SMALL, size)

        def held() -> tuple:
            size = client.get_collection("memories").config.params.vectors.size
            return size, client.collection_exists("memories__embedding")

    before = held()
    with pytest.raises(EmbeddingSpaceError, match="4-dimensional"):
        open(8)
    assert held() == before  # Neither its schema nor a record changed.
    open(4)


def test_setup_checks_the_store_the_settings_open_not_one_of_the_same_name(tmp_path: Path) -> None:
    """The memories table recorded for OpenAI's embedding in the workspace: the bundle naming
    Google's for a Qdrant store or a directory of its own opens another store, and is fine;
    for that same table, wherever its settings name it, it is refused."""
    from alphaavatar.agents.utils.vdb.space import recorded_conflicts
    from alphaavatar.agents.workspace import WorkspacePaths

    workspace = WorkspacePaths.from_root(tmp_path / "avatar")
    default = workspace.data.indexes.namespace("memory").backend("lancedb").root
    # Recorded while the settings named the default directory.
    Lance(default).open(SMALL)

    def found(modules=MODULES, **vdb_config) -> list[str]:
        settings = {
            "memory": {
                "plugin": "default",
                "vdb_config": {"collection_name": "memories", "embedding": OTHER, "url": None}
                | vdb_config,
            }
        }
        return recorded_conflicts(settings, workspace, modules)

    assert found(url="https://vectors.invalid:6333") == []  # Qdrant: not the LanceDB table.
    assert found(client_path=str(tmp_path / "own")) == []  # A directory of its own.
    assert len(found()) == 1  # The workspace's table, the settings naming no directory.
    assert len(found(client_path=str(default))) == 1  # The same table, named by its directory.
    assert found(modules={}) == []  # No plugin the build installs: start checks what it opens.

    # Moved aside: the default directory holds no table, and the one moved is no store.
    default.rename(default.with_name("lancedb-backup"))
    assert found() == []


def test_setup_tells_each_table_once_and_for_the_section_naming_it(tmp_path: Path) -> None:
    """Memory, Persona and MCP sharing a directory: each record is the table of the setting
    that recorded it, told once, for that section."""
    from alphaavatar.agents.utils.vdb.space import recorded_conflicts
    from alphaavatar.agents.workspace import WorkspacePaths

    shared = tmp_path / "shared"
    Lance(shared).open(SMALL, name="memories")
    profiles = Lance(shared)
    space = EmbeddingSpace.configured(SMALL, 4)
    setting = "persona.vdb_config.profiler_collection_name"
    profiles.client.claim_space("profiles", space, setting=setting, ensure=lambda: None)
    settings = {
        "memory": {
            "plugin": "default",
            "vdb_config": {
                "collection_name": "memories",
                "client_path": str(shared),
                "embedding": OTHER,
            },
        },
        "persona": {
            "plugin": "default",
            "vdb_config": {
                "profiler_collection_name": "profiles",
                "client_path": str(shared),
                "embedding": OTHER,
            },
        },
        "tools": {
            "mcp": {
                "plugin": "default",
                "enabled": True,
                # Memory's table, named by a setting of the same name: memory's still.
                "vdb_config": {
                    "collection_name": "memories",
                    "client_path": str(shared),
                    "embedding": OTHER,
                },
            }
        },
    }
    found = recorded_conflicts(settings, WorkspacePaths.from_root(tmp_path / "avatar"), MODULES)
    assert [line.split(" holds ")[0] for line in found] == [
        f"LanceDB table 'memories' in {shared}",
        f"LanceDB table 'profiles' in {shared}",
    ]
    assert "give memory.vdb_config.collection_name" in found[0]
    assert "give persona.vdb_config.profiler_collection_name" in found[1]
    # Persona naming memory's table for its own: not the table its runner recorded.
    settings["persona"]["vdb_config"]["profiler_collection_name"] = "memories"
    found = recorded_conflicts(settings, WorkspacePaths.from_root(tmp_path / "avatar"), MODULES)
    assert len(found) == 1 and "give memory.vdb_config.collection_name" in found[0]


@pytest.mark.parametrize("models", ["same", "different"])
def test_hosts_registering_one_qdrant_store_at_once_never_both_take_it_for_two_models(
    models: str,
) -> None:
    """Two Hosts, one Qdrant: each has read that the store is unrecorded before either records
    it. The same model: both open it. Two models: never both; what stays recorded is the one
    that opened it, never overwritten."""
    from qdrant_client import QdrantClient

    shared = QdrantClient(location=":memory:")
    held = Interleaved(shared, threading.Barrier(2), ("collection_exists", "memories", 1, True))
    second = SMALL if models == "same" else OTHER
    ended = race(lambda: qdrant_open(held, SMALL), lambda: qdrant_open(held, second))
    opened = [
        embedding for embedding, end in zip((SMALL, second), ended, strict=True) if end is None
    ]
    if models == "same":
        assert ended == [None, None]
    else:
        assert len(opened) <= 1 and all(
            isinstance(end, EmbeddingSpaceError) for end in ended if end
        )
    records = [
        p.payload for p in shared.scroll("memories__embedding", limit=10, with_payload=True)[0]
    ]
    assert {r["model"] for r in records} == {e["model"] for e in opened}


def test_hosts_registering_into_an_empty_record_at_once_never_both_take_it() -> None:
    """A record collection left empty by a stopped Host, two Hosts of two models registering at
    once, each holding until both have recorded: neither opens the store."""
    from qdrant_client import QdrantClient

    shared = QdrantClient(location=":memory:")
    qdrant_open(shared, SMALL, name="warmup")  # The record collection's own layout, to copy.
    params = shared.get_collection("warmup__embedding").config.params.vectors
    shared.create_collection("memories__embedding", vectors_config=params)
    # Both have read it empty, both recorded before either reads again, and both read again
    # before either takes its own back.
    held = Interleaved(
        shared,
        threading.Barrier(2),
        ("scroll", "memories__embedding", 1, True),
        ("scroll", "memories__embedding", 2, False),
        ("scroll", "memories__embedding", 2, True),
    )
    ended = race(lambda: qdrant_open(held, SMALL), lambda: qdrant_open(held, OTHER))
    assert all(isinstance(end, EmbeddingSpaceError) for end in ended), ended
    assert shared.scroll("memories__embedding", limit=10)[0] == []  # Each took its own back.


@pytest.mark.parametrize("models", ["same", "different"])
def test_hosts_registering_one_lancedb_table_at_once_never_both_take_it_for_two_models(
    models: str, tmp_path: Path
) -> None:
    store = Lance(tmp_path)
    # Held in the client's own calls, as its store's opening makes them: each has read that
    # no record is there before either records.
    store.client.table_exists = Interleaved(
        store.client, threading.Barrier(2), ("table_exists", "memories", 1, True)
    ).table_exists
    second = SMALL if models == "same" else OTHER
    ended = race(lambda: store.open(SMALL), lambda: store.open(second))
    opened = [
        embedding for embedding, end in zip((SMALL, second), ended, strict=True) if end is None
    ]
    if models == "same":
        assert ended == [None, None]
    else:
        assert len(opened) == 1 and isinstance(
            [end for end in ended if end][0], EmbeddingSpaceError
        )
    assert store.record()["model"] == opened[0]["model"]


def test_hosts_registering_one_model_for_a_store_made_before_records_both_open_it() -> None:
    """A store made before records, holding vectors; two Hosts of one model register it at
    once, each reaching the record's creation before either makes it: both open the store."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    shared = QdrantClient(location=":memory:")
    shared.create_collection(
        "memories", vectors_config=VectorParams(size=4, distance=Distance.COSINE)
    )
    shared.upsert("memories", points=[PointStruct(id=1, vector=[1.0, 0.0, 0.0, 0.0])])
    held = Interleaved(
        shared, threading.Barrier(2), ("create_collection", "memories__embedding", 1, False)
    )
    assert race(lambda: qdrant_open(held, SMALL), lambda: qdrant_open(held, SMALL)) == [None, None]
    records = [
        p.payload for p in shared.scroll("memories__embedding", limit=10, with_payload=True)[0]
    ]
    # Each recorded it, of one model: records of one space.
    assert {(r["model"], r["assumed"]) for r in records} == {("text-embedding-3-small", True)}
    assert shared.count("memories", exact=True).count == 1


def test_records_an_earlier_version_wrote_are_kept_to_and_never_written(tmp_path: Path) -> None:
    """Records as the version before marks wrote them, a JSON file beside the table and point 0
    of a collection with one unnamed vector: read as records, their model kept to, at start and
    by setup, and never rewritten."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from alphaavatar.agents.utils.vdb.space import recorded_conflicts
    from alphaavatar.agents.workspace import WorkspacePaths

    workspace = WorkspacePaths.from_root(tmp_path / "avatar")
    earlier = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": None,
        "size": 4,
    }
    store = Lance(workspace.data.indexes.namespace("memory").backend("lancedb").root)
    store.client.create_table("memories", ROWS)
    record = store.client.path / "memories.embedding.json"
    record.write_text(json.dumps(earlier | {"store": "memories", "setting": SETTING}))
    written = record.read_bytes()
    store.open(SMALL)
    with pytest.raises(EmbeddingSpaceError):
        store.open(OTHER)
    settings = {
        "memory": {
            "plugin": "default",
            "vdb_config": {"collection_name": "memories", "embedding": OTHER, "url": None},
        }
    }
    assert len(recorded_conflicts(settings, workspace, MODULES)) == 1
    assert record.read_bytes() == written

    client = QdrantClient(location=":memory:")
    client.create_collection(
        "memories", vectors_config=VectorParams(size=4, distance=Distance.COSINE)
    )
    client.create_collection(
        "memories__embedding", vectors_config=VectorParams(size=1, distance=Distance.DOT)
    )
    payload = earlier | {"store": "memories", "setting": SETTING}
    client.upsert("memories__embedding", points=[PointStruct(id=0, vector=[1.0], payload=payload)])
    qdrant_open(client, SMALL)
    with pytest.raises(EmbeddingSpaceError):
        qdrant_open(client, OTHER)
    points = client.scroll("memories__embedding", with_payload=True)[0]
    assert [(point.id, point.payload) for point in points] == [(0, payload)]


def test_a_host_that_read_no_record_before_another_recorded_never_overwrites_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host B read that the table was unrecorded just before Host A recorded it, then records
    another model: A's record stays, and B refuses."""
    store = Lance(tmp_path)
    store.open(SMALL)  # Host A.
    first = store.record()
    exists, stale = Path.exists, []

    def read_before_a(self: Path, *args, **kwargs) -> bool:
        if self.name == "memories.embedding.json" and not stale:
            stale.append(self)
            return False  # What B saw, before A recorded.
        return exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", read_before_a)
    with pytest.raises(EmbeddingSpaceError, match="holds vectors of openai"):
        store.open(OTHER)  # Host B.
    assert stale and store.record() == first


def test_a_qdrant_host_that_read_no_record_before_another_recorded_takes_its_own_back() -> None:
    from qdrant_client import QdrantClient

    shared = QdrantClient(location=":memory:")
    qdrant_open(shared, SMALL)  # Host A.
    (first,) = shared.scroll("memories__embedding", with_payload=True, with_vectors=True)[0]

    class Stale:
        """Host B's client: its first read of the record, from before A recorded."""

        def __init__(self) -> None:
            self.read = False

        def __getattr__(self, name: str):
            if name in ("scroll", "retrieve") and not self.read:
                self.read = True  # Read by listing, or by its one point, as versions did.
                empty = ([], None) if name == "scroll" else []
                return lambda *args, **kwargs: empty
            return getattr(shared, name)

    with pytest.raises(EmbeddingSpaceError, match="holds vectors of openai"):
        qdrant_open(Stale(), OTHER)  # Host B.
    points = shared.scroll("memories__embedding", with_payload=True, with_vectors=True)[0]
    assert [(p.id, p.payload, p.vector) for p in points] == [
        (first.id, first.payload, first.vector)
    ]


def test_a_host_taking_its_record_back_never_takes_another_s_of_its_model() -> None:
    """Host A opened the store for its model. Host B, of that model, read before A recorded and
    records too, as Host C records another model: B finds C's, takes its own back and refuses;
    A's record stays, so C, and any Host after, finds it and refuses."""
    from qdrant_client import QdrantClient

    shared = QdrantClient(location=":memory:")
    qdrant_open(shared, SMALL)  # Host A.
    (a,) = shared.scroll("memories__embedding", with_payload=True)[0]

    class Racing:
        """Host B's client: its first read from before A recorded; C records right after B."""

        def __init__(self) -> None:
            self.read, self.recorded = False, False

        def __getattr__(self, name: str):
            if name in ("scroll", "retrieve") and not self.read:
                self.read = True
                empty = ([], None) if name == "scroll" else []
                return lambda *args, **kwargs: empty
            if name == "upsert" and not self.recorded:
                self.recorded = True

                def upsert(*args, **kwargs):
                    shared.upsert(*args, **kwargs)
                    point = PointStruct(id=str(uuid.uuid4()), vector={LAYOUT: [1.0]}, payload=c)
                    shared.upsert("memories__embedding", points=[point])  # Host C's.

                return upsert
            return getattr(shared, name)

    from qdrant_client.models import PointStruct

    from alphaavatar.agents.utils.vdb.qdrant import LAYOUT

    c = EmbeddingSpace.configured(OTHER, 4).record(store="memories", setting=SETTING)
    with pytest.raises(EmbeddingSpaceError):
        qdrant_open(Racing(), SMALL)  # Host B.
    points = shared.scroll("memories__embedding", with_payload=True)[0]
    assert sorted(p.payload["model"] for p in points) == [
        "text-embedding-004",
        "text-embedding-3-small",
    ]
    assert a.id in [p.id for p in points]  # A's record, which A opened the store by, stays.
    with pytest.raises(EmbeddingSpaceError):
        qdrant_open(shared, OTHER)  # Host C, and any after it, finds A's record.


"""Review of 2026-11-25: three Hosts, and what a Host may rely on"""


class Hosts:
    """Hosts sharing one store, each on a thread of its own, held at the points the test names
    — before or after a call of its client, ``"before upsert memories__embedding 1"`` its first
    upsert there — until the test lets it on: the test orders what each has done when another
    goes on, whatever the threads' timing."""

    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._stops: dict[str, set[str]] = {}
        self._held: dict[str, str | None] = {}
        self._free: set[str] = set()
        self._threads: dict[str, threading.Thread] = {}
        self._counts = threading.local()
        self.ended: dict[str, BaseException | None] = {}

    def at(self, point: str) -> None:
        """In a Host's thread: held at ``point`` if it is one of its stops."""
        name = threading.current_thread().name
        if point not in self._stops.get(name, ()) or name in self._free:
            return
        with self._changed:
            self._held[name] = point
            self._changed.notify_all()
            self._changed.wait_for(lambda: self._held[name] is None, timeout=20)

    def wrap(self, function, name: str):
        """``function`` as the Hosts call it: each call a point before it and after it,
        ``"before <name> <n>"``, numbered by the Host's calls of it."""

        def call(*args, **kwargs):
            counts = self._counts.__dict__.setdefault("counts", {})
            counts[name] = n = counts.get(name, 0) + 1
            self.at(f"before {name} {n}")
            try:
                return function(*args, **kwargs)
            finally:
                self.at(f"after {name} {n}")

        return call

    def client(self, client):
        """``client`` as the Hosts call it, each method on each collection named
        ``"<method> <collection>"``."""
        hosts = self

        class Held:
            def __getattr__(self, method: str):
                found = getattr(client, method)
                if not callable(found):
                    return found

                def call(*args, **kwargs):
                    on = args[0] if args else kwargs.get("collection_name")
                    return hosts.wrap(found, f"{method} {on}")(*args, **kwargs)

                return call

        return Held()

    def start(self, name: str, opening, *stops: str) -> None:
        def run() -> None:
            try:
                opening()
                self.ended[name] = None
            except BaseException as error:
                self.ended[name] = error

        self._stops[name], self._held[name] = set(stops), None
        self._threads[name] = threading.Thread(target=run, name=name)
        self._threads[name].start()

    def until(self, name: str, point: str) -> None:
        """Wait until ``name`` is held at ``point``."""
        with self._changed:
            reached = self._changed.wait_for(lambda: self._held[name] == point, timeout=20)
        assert reached, f"{name} never reached {point!r}; it ended with {self.ended.get(name)!r}"

    def go(self, name: str) -> None:
        with self._changed:
            self._held[name] = None
            self._changed.notify_all()

    def finish(self, name: str) -> BaseException | None:
        """Let ``name`` on past every stop, to its end: how it ended, None for opened."""
        self._free.add(name)
        self.go(name)
        self._threads[name].join(timeout=60)
        assert not self._threads[name].is_alive(), f"{name} did not end"
        return self.ended[name]


READ = "before upsert memories__embedding 1"  # Has read what is recorded, recorded nothing.
WROTE = "after upsert memories__embedding 1"  # Has recorded, not read again.


def qdrant_records(client, *, with_vectors: bool = False) -> list:
    points, offset = [], None
    while True:
        page, offset = client.scroll(
            "memories__embedding", limit=100, offset=offset, with_vectors=with_vectors
        )
        points += page
        if offset is None:
            return sorted(points, key=lambda point: str(point.id))


def test_a_host_never_relies_on_a_record_its_host_may_still_take_back() -> None:
    """C, of another model, has read that nothing is recorded. A records, not yet reading it
    again; B, of A's model, opens beside A's record. C records; A, reading again, finds C's.
    Whatever A then does, B's model and C's never both have the store: C is refused, B's
    record stays as it was."""
    from qdrant_client import QdrantClient

    shared = QdrantClient(location=":memory:")
    hosts = Hosts()
    held = hosts.client(shared)
    hosts.start("C", lambda: qdrant_open(held, OTHER), READ, WROTE)
    hosts.until("C", READ)
    hosts.start("A", lambda: qdrant_open(held, SMALL), WROTE)
    hosts.until("A", WROTE)
    hosts.start("B", lambda: qdrant_open(held, SMALL))
    assert hosts.finish("B") is None
    decided = [(p.id, p.payload) for p in qdrant_records(shared) if not p.payload.get("pending")]
    hosts.go("C")
    hosts.until("C", WROTE)
    a, c = hosts.finish("A"), hosts.finish("C")

    assert isinstance(c, EmbeddingSpaceError), c
    assert a is None or isinstance(a, EmbeddingSpaceError), a
    left = [(p.id, p.payload) for p in qdrant_records(shared)]
    assert {payload["model"] for _, payload in left} == {"text-embedding-3-small"}
    assert decided and left == decided  # B's own record as it was; A's and C's taken back.


@pytest.mark.parametrize("kind", ["failed", "interrupted", "killed"])
def test_a_host_stopped_while_recording_takes_its_record_back_or_leaves_it_untrusted(
    kind: str,
) -> None:
    """A Host whose second read fails, or is interrupted, takes its record back; one killed
    then leaves it pending. Either way it opened nothing, and on retry it opens the store;
    another model is refused."""
    from qdrant_client import QdrantClient

    shared = QdrantClient(location=":memory:")

    class Failing:
        def __init__(self) -> None:
            self.recorded = False

        def __getattr__(self, name: str):
            if name == "upsert":
                self.recorded = True
            if name == "scroll" and self.recorded:  # Reading again, after recording.
                raise KeyboardInterrupt if kind == "interrupted" else ConnectionError("gone")
            if name == "delete" and kind == "killed":
                raise ConnectionError("the server went away")
            return getattr(shared, name)

    with pytest.raises(KeyboardInterrupt if kind == "interrupted" else ConnectionError):
        qdrant_open(Failing(), SMALL)
    left = qdrant_records(shared)
    assert (len(left), shared.collection_exists("memories")) == ((kind == "killed") * 1, False)

    qdrant_open(shared, SMALL)  # On retry.
    with pytest.raises(EmbeddingSpaceError):
        qdrant_open(shared, OTHER)
    assert {p.payload["model"] for p in qdrant_records(shared)} == {"text-embedding-3-small"}


def test_records_of_many_hosts_are_read_to_the_last() -> None:
    """More records than a page holds, the last of another model: never left unread, and the
    store's own model reopens it however many there are."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct

    from alphaavatar.agents.utils.vdb.qdrant import LAYOUT

    client = QdrantClient(location=":memory:")
    qdrant_open(client, SMALL, name="warmup")  # The record collection's own layout, to copy.
    params = client.get_collection("warmup__embedding").config.params.vectors
    client.create_collection("memories__embedding", vectors_config=params)
    small = EmbeddingSpace.configured(SMALL, 4).record(store="memories", setting=SETTING)
    other = EmbeddingSpace.configured(OTHER, 4).record(store="memories", setting=SETTING)
    many = [
        PointStruct(id=str(uuid.UUID(int=n + 1)), vector={LAYOUT: [1.0]}, payload=small)
        for n in range(600)
    ]
    client.upsert("memories__embedding", points=many)
    last = PointStruct(id=str(uuid.UUID(int=2**128 - 1)), vector={LAYOUT: [1.0]}, payload=other)
    client.upsert("memories__embedding", points=[last])
    with pytest.raises(EmbeddingSpaceError, match="google text-embedding-004"):
        qdrant_open(client, SMALL)

    client.delete("memories__embedding", points_selector=[last.id])
    for _ in range(3):
        qdrant_open(client, SMALL)  # Reopened: nothing more recorded.
    assert len(qdrant_records(client)) == 600


@pytest.mark.parametrize("models", ["same", "different"])
def test_three_hosts_recording_at_once_open_the_store_for_one_model_only(models: str) -> None:
    """Three Hosts, each having read that nothing is recorded, all recording before any reads
    again, then reading again one by one: of one model, all open it, and a fourth records
    nothing more. With another model among them, A and B find it recorded and take theirs back;
    C, reading last, finds only its own: one model has the store, never two."""
    from qdrant_client import QdrantClient

    shared = QdrantClient(location=":memory:")
    hosts = Hosts()
    held = hosts.client(shared)
    third = SMALL if models == "same" else OTHER
    for name, embedding in (("A", SMALL), ("B", SMALL), ("C", third)):
        hosts.start(name, lambda embedding=embedding: qdrant_open(held, embedding), READ, WROTE)
        hosts.until(name, READ)
    for name in "ABC":
        hosts.go(name)
        hosts.until(name, WROTE)
    ended = {name: hosts.finish(name) for name in "ABC"}

    if models == "same":
        assert ended == {"A": None, "B": None, "C": None}
        records = [point.payload for point in qdrant_records(shared)]
        assert {r["model"] for r in records} == {"text-embedding-3-small"}
        assert not [r for r in records if r.get("pending")]
        qdrant_open(shared, SMALL)  # A fourth Host.
        assert [point.payload for point in qdrant_records(shared)] == records
    else:
        assert isinstance(ended["A"], EmbeddingSpaceError), ended
        assert isinstance(ended["B"], EmbeddingSpaceError) and ended["C"] is None, ended
        records = [point.payload for point in qdrant_records(shared)]
        assert [(r["model"], r.get("pending")) for r in records] == [("text-embedding-004", None)]
        with pytest.raises(EmbeddingSpaceError):
            qdrant_open(shared, SMALL)  # A retry of A's model.
        qdrant_open(shared, OTHER)


def test_a_lancedb_host_never_relies_on_a_record_it_did_not_see_placed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The three Hosts of the Qdrant case on one LanceDB table: its one record, placed once and
    never taken back, decides; C is refused, and the record is A's, as placed."""
    store = Lance(tmp_path)
    hosts = Hosts()
    monkeypatch.setattr(os, "link", hosts.wrap(os.link, "link"))
    hosts.start("C", lambda: store.open(OTHER), "before link 1", "after link 1")
    hosts.until("C", "before link 1")
    hosts.start("A", lambda: store.open(SMALL), "after link 1")
    hosts.until("A", "after link 1")
    placed = store.record()
    hosts.start("B", lambda: store.open(SMALL))
    assert hosts.finish("B") is None
    hosts.go("C")
    hosts.until("C", "after link 1")
    assert hosts.finish("A") is None
    assert isinstance(hosts.finish("C"), EmbeddingSpaceError)
    assert placed["model"] == "text-embedding-3-small" and store.record() == placed


def test_three_hosts_reading_one_another_s_records_at_once_all_refuse_then_one_reopens() -> None:
    """Three Hosts of two models, each having recorded, all reading again before any takes its
    own back: each finds another model's, so none opens the store; all their records taken
    back, a retry opens it."""
    from qdrant_client import QdrantClient

    shared = QdrantClient(location=":memory:")
    hosts = Hosts()
    held = hosts.client(shared)
    again = "before delete memories__embedding 1"  # Has read again, taken nothing back yet.
    for name, embedding in (("A", SMALL), ("B", SMALL), ("C", OTHER)):
        hosts.start(name, lambda embedding=embedding: qdrant_open(held, embedding), WROTE, again)
        hosts.until(name, WROTE)
    for name in "ABC":
        hosts.go(name)
        hosts.until(name, again)
    ended = {name: hosts.finish(name) for name in "ABC"}
    assert all(isinstance(end, EmbeddingSpaceError) for end in ended.values()), ended
    assert qdrant_records(shared) == [] and not shared.collection_exists("memories")
    qdrant_open(shared, SMALL)  # A retry.
    with pytest.raises(EmbeddingSpaceError):
        qdrant_open(shared, OTHER)


"""Review of 2026-11-26: a record whose deciding may have been done"""


@pytest.mark.parametrize("lost", ["connection", "interrupt", "unsent"])
def test_a_record_whose_deciding_may_be_done_is_never_taken_back(lost: str) -> None:
    """A decides its record, held before the answer comes back; B opens the store beside it.
    Then A's answer is lost, or A is interrupted: its record stays decided, so C, of another
    model, is refused, and B's record and data stay as they were. Had A's deciding write never
    reached the store, its record would stay pending: no Host relies on it, C is refused all
    the same, and A, retrying, opens the store."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct

    shared = QdrantClient(location=":memory:")
    hosts = Hosts()
    held = hosts.client(shared)
    deciding = "before upsert memories__embedding 2"  # Its first write recorded it pending.

    class Lost:
        """A's client: its deciding write done, or not, and its answer lost."""

        def __getattr__(self, name: str):
            found = getattr(held, name)
            if name != "upsert":
                return found

            def upsert(*args, **kwargs):
                pending = any(p.payload.get("pending") for p in kwargs["points"])
                if not pending and lost == "unsent":
                    hosts.at(deciding)
                    raise ConnectionError("never sent")
                result = found(*args, **kwargs)
                if not pending:
                    raise KeyboardInterrupt if lost == "interrupt" else ConnectionError("lost")
                return result

            return upsert

    stop = deciding if lost == "unsent" else "after upsert memories__embedding 2"
    hosts.start("A", lambda: qdrant_open(Lost(), SMALL), stop)
    hosts.until("A", stop)
    if lost != "unsent":
        hosts.start("B", lambda: qdrant_open(held, SMALL))
        assert hosts.finish("B") is None
        point = PointStruct(id=1, vector=[1.0, 0.0, 0.0, 0.0], payload={"text": "B's"})
        shared.upsert("memories", points=[point])
    kept = [(p.id, p.payload) for p in qdrant_records(shared)]
    ended = hosts.finish("A")

    assert isinstance(ended, KeyboardInterrupt if lost == "interrupt" else ConnectionError)
    assert [(p.id, p.payload) for p in qdrant_records(shared)] == kept
    assert [payload.get("pending") for _, payload in kept] == [True if lost == "unsent" else None]
    with pytest.raises(EmbeddingSpaceError):
        qdrant_open(shared, OTHER)  # C.
    assert [(p.id, p.payload) for p in qdrant_records(shared)] == kept
    if lost == "unsent":
        qdrant_open(shared, SMALL)  # A, retrying.
    else:
        (data,) = shared.scroll("memories", with_payload=True, with_vectors=True)[0]
        assert (data.id, data.payload, data.vector) == (1, {"text": "B's"}, [1.0, 0.0, 0.0, 0.0])
