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
import threading
import uuid
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
        "alphaavatar.embedding_space": 1,
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": None,
        "size": 4,
        "store": "memories",
        "setting": SETTING,
        "client_path": None,
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

    indexes = tmp_path / "indexes"
    default = indexes / "memory/lancedb"
    Lance(default).open(SMALL)

    def found(**vdb_config) -> list[str]:
        settings = {
            "memory": {
                "plugin": "default",
                "vdb_config": {"collection_name": "memories", "embedding": OTHER, "url": None}
                | vdb_config,
            }
        }
        return recorded_conflicts(settings, [indexes])

    assert found(url="https://vectors.invalid:6333") == []  # Qdrant: not the LanceDB table.
    assert found(client_path=str(tmp_path / "own")) == []  # A directory of its own.
    assert len(found()) == 1  # The workspace's table.
    assert len(found(client_path=str(default))) == 1  # The same table, named by its directory.


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

    earlier = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": None,
        "size": 4,
    }
    store = Lance(tmp_path / "indexes/memory/lancedb")
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
    assert len(recorded_conflicts(settings, [tmp_path / "indexes"])) == 1
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
