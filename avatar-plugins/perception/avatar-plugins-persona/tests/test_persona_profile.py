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
"""Persona profile merge order, idempotent saves, LanceDB user isolation on local files, and
speaker vectors kept per speaker model in both vector stores."""

from __future__ import annotations

import hashlib
import itertools
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from alphaavatar.agents.persona.schemas import UserProfile, UserRuntimeState
from alphaavatar.agents.runtime.inference import RunnerLaunch
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.session import Participant
from alphaavatar.core.time import RuntimeClock
from alphaavatar.plugins.persona.cache import DefaultPersonaCache
from alphaavatar.plugins.persona.processors.speaker.cache import SpeakerCache
from alphaavatar.plugins.persona.profile import UserProfileDetails
from alphaavatar.plugins.persona.profile.serialization import (
    flatten_profile_items,
    merge_profile_field,
    merge_profile_items,
    rebuild_profile_items,
)
from alphaavatar.plugins.persona.storage.runtime_state import RuntimeStateStore
from alphaavatar.plugins.persona.storage.vdb.lancedb import LanceDBRunner
from alphaavatar.plugins.persona.storage.vdb.qdrant import QdrantRunner

T0 = datetime(2026, 11, 2, 8, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def entry(value: str, source: str, minutes: int) -> dict:
    return {"value": value, "source": source, "updated_at": at(minutes).isoformat()}


@pytest.mark.parametrize(
    ("stored", "incoming", "winner"),
    [
        (("female", "chat", 1), ("male", "speech", 9), "female"),
        (("female", "chat", 1), ("male", "face", 9), "female"),
        (("female", "face", 1), ("male", "speech", 9), "female"),
        (("female", "speech", 5), ("male", "face", 1), "male"),
        (("female", "face", 5), ("male", "chat", 1), "male"),
        (("female", "speech", 5), ("male", "speech", 1), "female"),
        (("female", "speech", 5), ("male", "speech", 9), "male"),
    ],
)
def test_profile_source_priority_is_chat_then_face_then_speech(
    stored: tuple, incoming: tuple, winner: str
) -> None:
    value, _ = merge_profile_field(
        entry(*stored), {}, {**entry(*incoming), "value": entry(*incoming)}
    )
    assert value["value"] == winner


def test_a_stored_vector_is_read_at_unit_length_and_one_without_a_length_is_refused() -> None:
    profile = UserProfile(speaker_vector=[3.0, 4.0], face_vector=[0.0, 2.0])
    assert profile.speaker_vector == pytest.approx([0.6, 0.8])
    assert profile.face_vector == pytest.approx([0.0, 1.0])
    for invalid in ([0.0, 0.0], [float("nan"), 1.0]):
        with pytest.raises(ValueError, match="finite, nonzero length"):
            UserProfile(speaker_vector=invalid)


def test_sensor_attributes_never_override_a_chat_fact_held_by_the_cache() -> None:
    participant = Participant(participant_id="p1", user_id="alice", joined_at=RuntimeClock().now())
    cache = DefaultPersonaCache(participant=participant)
    cache.set_base(UserProfile(details=UserProfileDetails(gender=entry("female", "chat", 0))))
    attributes = {
        "logits_age": np.array([[0.3]], dtype=np.float32),
        "logits_gender": np.array([[0.0, 0.0, 9.0]], dtype=np.float32),
    }
    cache.profile_details = SpeakerCache().update_profile_detail(
        cache.profile_details, attributes, updated_at=at(30)
    )
    details = cache.profile.details
    assert (details.gender.value, details.gender.source) == ("female", "chat")
    assert (details.age.value, details.age.source) == ("25-34 years old", "speech")
    # Only the sensor-owned field is an observation to persist; the chat fact is untouched.
    assert cache.detail_fields == {"age"}


def change(op: str, value: str, minutes: int) -> dict:
    (item,) = flatten_profile_items(
        "alice",
        {"languages": None},
        fields=frozenset({"languages"}),
        updated_at={"languages": at(minutes)},
        operations={
            "languages": [
                {
                    "op": op,
                    "value": value,
                    "list": True,
                    "updated_at": at(minutes).isoformat(),
                    "sequence": 0,
                    "id": f"{op}-{value}",
                }
            ]
        },
    )
    return item


def test_out_of_order_list_increments_converge_and_redelivery_is_idempotent() -> None:
    changes = [change("append", "English", 1), change("append", "French", 2)]
    changes.append(change("remove", "English", 3))
    for order in itertools.permutations(changes):
        rows: dict[str, dict] = {}
        for update in order:
            for merged in merge_profile_items(list(rows.values()), [update]):
                rows[merged["id"]] = merged
            # A repeated delivery of the same change is a no-op at the store boundary.
            assert merge_profile_items(list(rows.values()), [update]) == []
        languages = rebuild_profile_items(list(rows.values()))["languages"]
        assert [item["value"] for item in languages] == ["French"]


async def test_runtime_state_repeated_and_late_saves_are_idempotent(tmp_path: Path) -> None:
    store = RuntimeStateStore()
    user = WorkspacePaths.from_root(tmp_path / "avatar").users.get("alice")

    def login(session: str, minutes: int) -> UserRuntimeState:
        return UserRuntimeState(
            current_session_id=session,
            current_login_at=at(minutes),
            current_timezone="UTC",
            current_room_type="room",
        )

    for state in (login("s1", 1), login("s1", 1), login("s2", 5), login("s1", 1)):
        await store.save(user_path=user, runtime_state=state)

    loaded = await store.load(user_path=user)
    assert (loaded.current_session_id, loaded.last_session_id, loaded.login_count) == (
        "s2",
        "s1",
        2,
    )
    text = (user.runtime_dir / "runtime_state.md").read_text(encoding="utf-8")
    assert text.count("<!-- session_id:s1 -->") == text.count("<!-- session_id:s2 -->") == 1


def embed(text: str) -> list[float]:
    return [byte / 255 for byte in hashlib.sha256(text.encode()).digest()[:8]]


class OfflineEmbeddings:
    def embed_query(self, text: str) -> list[float]:
        return embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [embed(text) for text in texts]


class OfflineLanceDBRunner(LanceDBRunner):
    """The real local store; only the remote profiler embedding provider is replaced."""

    def _get_profiler_embeddings(self, config: dict) -> OfflineEmbeddings:
        return OfflineEmbeddings()


def call(runner: LanceDBRunner, op: str, **param) -> dict | None:
    result = runner.run(json.dumps({"op": op, "param": param}).encode())
    return json.loads(result) if result else None


def test_lancedb_user_predicates_isolate_quoted_identities_and_resave_idempotently(
    tmp_path: Path,
) -> None:
    runner = OfflineLanceDBRunner()
    runner.configure(
        RunnerLaunch(
            str(tmp_path / "avatar"),
            str(tmp_path / "models"),
            config=json.dumps(
                {
                    "persona": {
                        "profiler_collection_name": "profiles",
                        "speaker_collection_name": "speakers",
                        "face_collection_name": "faces",
                    }
                }
            ),
        )
    )
    runner.initialize()
    users = ["a", "a' OR user_id <> '", "b') OR ('1'='1", 'c" OR 1=1 --']
    saves = {}
    for index, user in enumerate(users):
        speaker, face = np.zeros(192), np.zeros(512)
        speaker[index] = face[index] = 1.0
        saves[user] = {
            "details_items": flatten_profile_items(
                user,
                {"name": entry(f"name-{index}", "chat", index)},
                fields=frozenset({"name"}),
                updated_at={"name": at(index)},
            ),
            "speaker_vector": speaker.tolist(),
            "face_vector": face.tolist(),
        }
        assert call(runner, "save", user_id=user, **saves[user])["error"] is None
    # Re-saving the same snapshot neither duplicates nor reorders stored rows.
    assert call(runner, "save", user_id=users[1], **saves[users[1]])["error"] is None

    for index, user in enumerate(users):
        loaded = call(runner, "load", user_id=user)
        (item,) = loaded["details_items"]
        assert item["metadata"]["user_id"] == user
        assert item["metadata"]["value"]["value"] == f"name-{index}"
        assert loaded["speaker_vector"] == pytest.approx(saves[user]["speaker_vector"])
        assert loaded["face_vector"] == pytest.approx(saves[user]["face_vector"])
    for invalid in ("", "a\0' OR '1'='1"):
        for op, param in (("load", {}), ("save", {"details_items": None, "speaker_vector": None})):
            with pytest.raises(ValueError, match="Invalid user identifier"):
                call(runner, op, user_id=invalid, **param)


class OfflineQdrantRunner(QdrantRunner):
    """The real local store; its LangChain profiler store needs LangChain embeddings."""

    def _get_profiler_embeddings(self, config: dict) -> OfflineEmbeddings:
        from langchain_core.embeddings import Embeddings

        class LangChainEmbeddings(OfflineEmbeddings, Embeddings):
            pass

        return LangChainEmbeddings()


def unit(index: int, size: int) -> list[float]:
    vector = [0.0] * size
    vector[index] = 1.0
    return vector


@pytest.mark.parametrize("backend", ["lancedb", "qdrant"])
def test_a_new_speaker_model_starts_its_own_vectors_and_keeps_faces_and_profiles(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The configured speaker collection held the previous model's vectors (the same 192
    # dimensions); with them sit the user's face vector and profile, written as before.
    names = {"profiler_collection_name": "profiles", "speaker_collection_name": "speakers"}
    if backend == "lancedb":
        import lancedb

        names |= {"face_collection_name": "faces", "client_path": str(tmp_path / "lancedb")}
        client = lancedb.connect(str(tmp_path / "lancedb"))
        rows = {"speakers": unit(0, 192), "faces": unit(0, 512)}
        for table, vector in rows.items():
            client.create_table(table, [{"id": "old", "user_id": "legacy", "vector": vector}])
        runner = OfflineLanceDBRunner()
    else:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        from alphaavatar.agents.utils.vdb import qdrant

        # Qdrant's in-process store, shared with the runner as its client would be.
        client = QdrantClient(location=":memory:")
        # Without a configured face collection, the faces are named after the speakers'.
        for table, vector in {"speakers": unit(0, 192), "speakers_face": unit(0, 512)}.items():
            client.create_collection(
                table, VectorParams(size=len(vector), distance=Distance.COSINE)
            )
            client.upsert(table, [PointStruct(id=1, vector=vector, payload={"user_id": "legacy"})])
        names |= {"url": "http://qdrant.test"}
        monkeypatch.setattr(qdrant, "get_client", lambda **_: client)
        runner = OfflineQdrantRunner()
    runner.configure(
        RunnerLaunch(
            str(tmp_path / "avatar"),
            str(tmp_path / "models"),
            config=json.dumps({"persona": names}),
        )
    )
    runner.initialize()
    details = flatten_profile_items(
        "legacy",
        {"name": entry("Ada", "chat", 1)},
        fields=frozenset({"name"}),
        updated_at={"name": at(1)},
    )
    saved = call(runner, "save", user_id="legacy", details_items=details, speaker_vector=None)
    assert saved["error"] is None

    # The previous model's vector is never searched, loaded or merged; the rest still reads.
    assert call(runner, "search_speaker_vector", speaker_vector=unit(0, 192), threshold=0.5) is None
    loaded = call(runner, "load", user_id="legacy")
    assert loaded["speaker_vector"] is None
    assert loaded["face_vector"] == pytest.approx(unit(0, 512))
    (item,) = loaded["details_items"]
    assert item["metadata"]["value"]["value"] == "Ada"

    # A vector of this model is saved, found and loaded in its own collection.
    assert (
        call(runner, "save", user_id="legacy", details_items=None, speaker_vector=unit(1, 192))[
            "error"
        ]
        is None
    )
    found = call(runner, "search_speaker_vector", speaker_vector=unit(1, 192), threshold=0.5)
    assert found["user_id"] == "legacy"
    assert call(runner, "load", user_id="legacy")["speaker_vector"] == pytest.approx(unit(1, 192))
    if backend == "lancedb":
        assert runner._client.open_table("speakers").count_rows() == 1
    else:
        assert runner._client.count("speakers").count == 1
        runner.close()
