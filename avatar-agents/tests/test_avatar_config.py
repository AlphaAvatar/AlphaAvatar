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
"""Avatar configuration validation: identity is explicit and validation changes nothing."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import lancedb
import pytest
import qdrant_client
from pydantic import ValidationError

# Imported at collection: the configuration package eagerly loads plugins and third-party
# libraries that adjust process variables while importing (O-2). That is an import side
# effect; validating a configuration afterwards must not write anything.
from alphaavatar.agents.configs import AvatarConfig

EMBEDDING = {"provider": "openai", "model": "text-embedding-3-small"}
SECTIONS = {
    "memory": {"vdb_config": {"collection_name": "memory", "embedding": EMBEDDING}},
    "persona": {
        "vdb_config": {
            "host": "vectors.internal",
            "port": 6333,
            "profiler_collection_name": "profiles",
            "speaker_collection_name": "speakers",
            "embedding": EMBEDDING,
        }
    },
    "tools": {
        "deepresearch": {"plugin": None},
        "rag": {"plugin": None},
        "mcp": {
            "enabled": True,
            "vdb_config": {"collection_name": "mcp", "embedding": EMBEDDING},
            "servers": {
                "docs": {
                    "url": "https://mcp.example/mcp",
                    "headers": {"Authorization": "Bearer <MCP_TEST_TOKEN>"},
                }
            },
        },
    },
}


@pytest.fixture
def vector_clients(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    constructed: list[str] = []

    def record(name: str):
        def refuse(*args: object, **kwargs: object) -> None:
            constructed.append(name)
            raise AssertionError(f"{name} constructed during configuration validation")

        return refuse

    monkeypatch.setattr(qdrant_client.QdrantClient, "__init__", record("QdrantClient"))
    monkeypatch.setattr(qdrant_client.AsyncQdrantClient, "__init__", record("AsyncQdrantClient"))
    monkeypatch.setattr(lancedb, "connect", record("lancedb.connect"))
    monkeypatch.setattr(lancedb, "connect_async", record("lancedb.connect_async"))
    return constructed


@pytest.fixture
def ambient() -> Iterator[dict[str, str]]:
    values = {
        "QDRANT_URL": "https://ambient-vectors.example:6333",
        "QDRANT_API_KEY": "ambient-vector-key",
        "MCP_TEST_TOKEN": "mcp-token",
    }
    # Restored before the isolation guard compares the process environment.
    with mock.patch.dict(os.environ, values):
        yield values


def assert_untouched(tmp_path: Path, environment: dict[str, str], constructed: list[str]) -> None:
    assert dict(os.environ) == environment
    assert constructed == []
    # The test owns cwd, HOME and TMPDIR; validation must leave all of them empty.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["home", "tmp"]
    assert not any((tmp_path / "home").iterdir()) and not any((tmp_path / "tmp").iterdir())


@pytest.mark.parametrize(
    ("value", "location"),
    [(SECTIONS, ("avatar",)), ({**SECTIONS, "avatar": {"name": "Assistant"}}, ("avatar", "id"))],
    ids=["missing-avatar", "missing-id"],
)
def test_missing_avatar_identity_is_rejected_instead_of_generated(
    value: dict[str, object],
    location: tuple[str, ...],
    tmp_path: Path,
    ambient: dict[str, str],
    vector_clients: list[str],
) -> None:
    environment = dict(os.environ)
    with pytest.raises(ValidationError) as rejected:
        AvatarConfig.model_validate(value)
    assert [(error["loc"], error["type"]) for error in rejected.value.errors()] == [
        (location, "missing")
    ]
    assert_untouched(tmp_path, environment, vector_clients)


def test_accepted_configuration_only_reads_its_inputs(
    tmp_path: Path, ambient: dict[str, str], vector_clients: list[str]
) -> None:
    environment = dict(os.environ)
    value = {**SECTIONS, "avatar": {"id": "alphaavatar_demo"}}
    first = AvatarConfig.model_validate(value)
    # Repeated validation in one process must not observe state left by the first one.
    second = AvatarConfig.model_validate(value)
    assert_untouched(tmp_path, environment, vector_clients)

    assert first.model_dump() == second.model_dump()
    assert first.avatar.workspace_root is None
    assert first.memory.vdb_config["url"] == ambient["QDRANT_URL"]
    assert first.memory.vdb_config["api_key"] == ambient["QDRANT_API_KEY"]
    # An explicit host keeps its endpoint; only the absent credential is captured.
    assert "url" not in first.persona.vdb_config
    assert first.persona.vdb_config["api_key"] == ambient["QDRANT_API_KEY"]
    headers = first.tools.mcp.servers["docs"]["headers"]
    assert headers == {"Authorization": "Bearer mcp-token"}
    for secret in ambient.values():
        assert secret not in repr(first)


def test_unresolved_placeholder_is_rejected_without_side_effects(
    tmp_path: Path, ambient: dict[str, str], vector_clients: list[str]
) -> None:
    del os.environ["MCP_TEST_TOKEN"]
    environment = dict(os.environ)
    with pytest.raises(ValidationError) as rejected:
        AvatarConfig.model_validate({**SECTIONS, "avatar": {"id": "alphaavatar_demo"}})
    assert [error["loc"] for error in rejected.value.errors()] == [("tools", "mcp")]
    assert "MCP_TEST_TOKEN" in str(rejected.value)
    assert_untouched(tmp_path, environment, vector_clients)
