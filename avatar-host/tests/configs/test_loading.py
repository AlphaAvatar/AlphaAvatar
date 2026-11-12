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
"""Application loading resolves paths and inputs once; restoring never re-reads the host."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest
import yaml
from config_samples import LOOP
from pydantic import ValidationError

import alphaavatar.plugins.mcp  # noqa: F401

# Imported at collection: plugin and third-party imports adjust process variables (O-2).
# Loading a configuration afterwards must leave the environment unchanged.
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.agents.runtime.inference import snapshot_inference_config
from alphaavatar.agents.utils.vdb.config import vdb_backend
from alphaavatar.host.configs import paths as application_paths
from alphaavatar.host.configs.loader import load_application, restore_application

EMBEDDING = {"provider": "openai", "model": "text-embedding-3-small"}


def avatar(identity: str, *, vector_key: str | None = None, token: str = "<MCP_TEST_TOKEN>"):
    memory = {"collection_name": f"{identity}_memory", "embedding": EMBEDDING}
    if vector_key is not None:
        memory |= {"url": f"https://{identity}.vectors.example", "api_key": vector_key}
    return {
        "avatar": {"id": identity},
        "loop": LOOP,
        "memory": {"vdb_config": memory},
        "persona": {
            "vdb_config": {
                "client_path": f"/srv/{identity}/persona-index",
                "profiler_collection_name": "profiles",
                "speaker_collection_name": "speakers",
                "face_collection_name": "faces",
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
                        "headers": {"Authorization": f"Bearer {token}"},
                    }
                },
            },
        },
    }


def write(path: Path, value: dict[str, object]) -> Path:
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return path


def tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def test_repeated_loads_keep_paths_and_credentials_separate(tmp_path: Path) -> None:
    home = tmp_path / "application"
    first = write(
        tmp_path / "alpha.yaml", avatar("alpha", vector_key="alpha-key", token="<ALPHA_TOKEN>")
    )
    second = write(
        tmp_path / "beta.yaml", avatar("beta", vector_key="beta-key", token="<BETA_TOKEN>")
    )
    before = tree(tmp_path)
    variables = {
        "ALPHAAVATAR_HOME": str(home),
        "ALPHA_TOKEN": "alpha-mcp",
        "BETA_TOKEN": "beta-mcp",
    }
    with mock.patch.dict(os.environ, variables):
        environment = dict(os.environ)
        alpha, beta, again = (load_application(path) for path in (first, second, first))
        assert dict(os.environ) == environment

    assert tree(tmp_path) == before
    assert alpha.workspace.root == home / "avatars" / "alpha"
    assert beta.workspace.root == home / "avatars" / "beta"
    assert (again.workspace, again.payload) == (alpha.workspace, alpha.payload)
    for loaded, own, foreign in ((alpha, "alpha", "beta"), (beta, "beta", "alpha")):
        payload = json.loads(loaded.payload)
        assert payload["memory"]["vdb_config"]["api_key"] == f"{own}-key"
        servers = payload["tools"]["mcp"]["servers"]
        assert servers["docs"]["headers"]["Authorization"] == f"Bearer {own}-mcp"
        assert f"{foreign}-key" not in loaded.payload and f"{foreign}-mcp" not in loaded.payload
        assert f"{own}-key" not in repr(loaded) and f"{own}-mcp" not in repr(loaded)


@pytest.mark.parametrize("source", ["yaml", "environment", "platform", "xdg"])
def test_application_home_precedence(source: str, tmp_path: Path) -> None:
    yaml_home, env_home, xdg = tmp_path / "yaml-home", tmp_path / "env-home", tmp_path / "xdg"
    value = avatar("alphaavatar_demo")
    variables = {"MCP_TEST_TOKEN": "token"}
    if source == "yaml":
        value["application"] = {"home": str(yaml_home)}
    if source in ("yaml", "environment"):
        variables["ALPHAAVATAR_HOME"] = str(env_home)
    if source == "xdg":
        variables["XDG_DATA_HOME"] = str(xdg)
    path = write(tmp_path / "avatar.yaml", value)
    before = tree(tmp_path)
    with mock.patch.dict(os.environ, variables):
        loaded = load_application(path)

    expected = {
        "yaml": yaml_home,
        "environment": env_home,
        "platform": tmp_path / "home" / ".local" / "share" / "alphaavatar",
        "xdg": xdg / "alphaavatar",
    }[source]
    assert loaded.paths.root == expected
    assert loaded.paths.cache.models_dir == expected / "cache" / "models"
    assert loaded.workspace.root == expected / "avatars" / "alphaavatar_demo"
    assert json.loads(loaded.payload)["application"]["home"] == str(expected)
    assert tree(tmp_path) == before


@pytest.mark.parametrize(
    ("platform", "variables", "expected"),
    [
        ("linux", {}, "home/.local/share/alphaavatar"),
        ("linux", {"XDG_DATA_HOME": "xdg"}, "xdg/alphaavatar"),
        ("darwin", {"XDG_DATA_HOME": "xdg"}, "home/Library/Application Support/AlphaAvatar"),
        ("win32", {"LOCALAPPDATA": "local"}, "local/AlphaAvatar"),
        ("win32", {}, "home/AppData/Local/AlphaAvatar"),
    ],
)
def test_platform_default_roots(
    platform: str,
    variables: dict[str, str],
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environ = {name: str(tmp_path / value) for name, value in variables.items()}
    with monkeypatch.context() as patch:
        patch.setattr(application_paths.sys, "platform", platform)
        root = application_paths.platform_application_root(environ, tmp_path / "home")
    assert root == tmp_path / expected


def test_explicit_cache_and_workspace_roots_survive_restore(tmp_path: Path) -> None:
    home, cache, workspace = tmp_path / "home-root", tmp_path / "cache-root", tmp_path / "ws"
    value = avatar("alphaavatar_demo")
    value["application"] = {"home": str(home), "cache_root": str(cache)}
    value["avatar"]["workspace_root"] = str(workspace)
    path = write(tmp_path / "avatar.yaml", value)
    before = tree(tmp_path)
    with mock.patch.dict(os.environ, {"MCP_TEST_TOKEN": "token"}):
        loaded = load_application(path)
    restored = restore_application(loaded.payload)

    assert tree(tmp_path) == before
    for config in (loaded, restored):
        assert config.paths.root == home
        assert config.paths.cache.root == cache
        assert config.paths.cache.models_dir == cache / "models"
        # An explicit workspace is the complete directory, never <root>/<id>.
        assert config.workspace.root == workspace
    assert loaded.previous_workspace_roots == ()
    assert json.loads(restored.payload) == json.loads(loaded.payload)


@pytest.mark.parametrize(
    ("variables", "change", "error"),
    [
        ({"AVATAR_WORK_DIR": "/srv/old"}, {}, "AVATAR_WORK_DIR"),
        ({"ALPHAAVATAR_MODEL_CACHE": "/srv/models"}, {}, "ALPHAAVATAR_MODEL_CACHE"),
        ({"ALPHAAVATAR_HOME": "relative/home"}, {}, "absolute"),
        ({}, {"application": {"home": "relative/home"}}, "absolute"),
        ({}, {"application": {"home": "/srv/home", "models": "/srv"}}, "Unknown application"),
        ({}, {"avatar": {"id": "alphaavatar_demo", "work_dir": "/srv"}}, "avatar.workspace_root"),
    ],
    ids=["work-dir-env", "model-cache-env", "relative-env", "relative-yaml", "unknown", "work-dir"],
)
def test_legacy_and_ambiguous_locations_are_refused(
    variables: dict[str, str], change: dict[str, object], error: str, tmp_path: Path
) -> None:
    path = write(tmp_path / "avatar.yaml", avatar("alphaavatar_demo") | change)
    before = tree(tmp_path)
    with mock.patch.dict(os.environ, variables | {"MCP_TEST_TOKEN": "token"}):
        with pytest.raises((ValueError, ValidationError), match=error):
            load_application(path)
    assert tree(tmp_path) == before


def test_restore_keeps_frozen_paths_and_inputs_after_the_environment_changes(
    tmp_path: Path,
) -> None:
    path = write(tmp_path / "avatar.yaml", avatar("alphaavatar_demo"))
    loaded_with = {
        "ALPHAAVATAR_HOME": str(tmp_path / "frozen-home"),
        "ALPHAAVATAR_MAX_SESSION_SECONDS": "30",
        "QDRANT_URL": "https://frozen-vectors.example:6333",
        "QDRANT_API_KEY": "frozen-key",
        "MCP_TEST_TOKEN": "frozen-token",
    }
    with mock.patch.dict(os.environ, loaded_with):
        loaded = load_application(path)
        absent = load_application(path, ["memory.vdb_config.url=null"])
    # Execution children restore after the Host environment may have changed completely.
    changed = {
        "ALPHAAVATAR_HOME": str(tmp_path / "other-home"),
        "AVATAR_WORK_DIR": str(tmp_path / "legacy"),
        "QDRANT_URL": "https://ambient-vectors.example:6333",
        "QDRANT_API_KEY": "ambient-key",
    }
    with mock.patch.dict(os.environ, changed):
        environment = dict(os.environ)
        restored = restore_application(loaded.payload)
        restored_absent = restore_application(absent.payload)
        assert dict(os.environ) == environment

    assert (restored.paths, restored.workspace) == (loaded.paths, loaded.workspace)
    assert restored.workspace.root == tmp_path / "frozen-home" / "avatars" / "alphaavatar_demo"
    assert restored.host.execution.max_session_seconds == 30
    assert json.loads(restored.payload) == json.loads(loaded.payload)
    assert snapshot_inference_config(restored.avatar) == snapshot_inference_config(loaded.avatar)
    memory = restored.avatar.memory.vdb_config
    assert (memory["url"], memory["api_key"]) == (
        "https://frozen-vectors.example:6333",
        "frozen-key",
    )
    headers = restored.avatar.tools.mcp.servers["docs"]["headers"]
    assert headers == {"Authorization": "Bearer frozen-token"}
    # A URL absent at load stays absent; a later ambient URL cannot switch backends.
    assert restored_absent.avatar.memory.vdb_config["url"] is None
    assert vdb_backend(restored_absent.avatar.memory.vdb_config) == "lancedb"
    assert json.loads(restored_absent.payload) == json.loads(absent.payload)
    assert "frozen-key" not in repr(restored) and "frozen-token" not in repr(restored)
    assert not (tmp_path / "frozen-home").exists() and not (tmp_path / "other-home").exists()
