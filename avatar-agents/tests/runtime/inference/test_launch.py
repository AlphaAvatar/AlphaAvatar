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
"""One frozen launch snapshot selects, configures and reaches every inference runner."""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import qdrant_client
from launch_runner_samples import LaunchProbeRunner, LaunchProbeTwinRunner

# Plugin imports register runner bootstraps; their import-time effects stay at collection (O-2).
import alphaavatar.plugins.mcp  # noqa: F401
from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.configs.runtime_config import InferenceConfig
from alphaavatar.agents.memory.schemas import MemoryContextRef, MemoryOwnerRef
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import (
    InferenceExecutor,
    InferenceRuntime,
    RunnerLaunch,
    bootstrap as inference_bootstrap,
    bootstrap_inference_runners,
    prepare_inference_runners,
    snapshot_inference_config,
)
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.session import SessionRuntime
from alphaavatar.plugins.mcp.enums import MCPOp
from alphaavatar.plugins.mcp.runner import lancedb_runner as mcp_lancedb
from alphaavatar.plugins.mcp.schemas import MCPRequest
from alphaavatar.plugins.memory.storage.vdb import (
    lancedb_runner as memory_lancedb,
    qdrant_runner as memory_qdrant,
)
from alphaavatar.plugins.persona.storage.vdb import (
    lancedb as persona_lancedb,
    qdrant as persona_qdrant,
)

HANG_GUARD = 30
PLAN = inference_bootstrap.INFERENCE_PLAN_ENV
EMBEDDING = {"provider": "openai", "model": "text-embedding-3-small"}
PERSONA_TABLES = {
    "profiler_collection_name": "profiles",
    "speaker_collection_name": "speakers",
    "face_collection_name": "faces",
}
MCP = {
    "enabled": True,
    "vdb_config": {"collection_name": "mcp_tools", "embedding": EMBEDDING},
    "servers": {
        "docs": {
            "url": "https://mcp.example/mcp",
            "headers": {"Authorization": "Bearer <MCP_TEST_TOKEN>"},
        }
    },
}
# Processors needing a Foundation provider are disabled; runner selection does not depend on them.
QUIET_MEMORY = {
    name: {"enabled": False} for name in ("retrieval", "conversation", "tool", "environment")
}
LOCAL = {
    "avatar": {"id": "alphaavatar_demo"},
    "memory": {
        "vdb_config": {"collection_name": "memories", "embedding": EMBEDDING},
        "init_config": QUIET_MEMORY,
    },
    "persona": {
        "vdb_config": {**PERSONA_TABLES, "embedding": EMBEDDING},
        "init_config": {"profiler": {"enabled": False}},
    },
    "tools": {"deepresearch": {"plugin": None}, "rag": {"plugin": None}},
}
REMOTE = {
    "avatar": {"id": "alphaavatar_demo"},
    "memory": {
        "vdb_config": {
            "collection_name": "memories",
            "url": "https://memory-vectors.example",
            "api_key": "memory-key",
            "embedding": EMBEDDING,
        },
        "init_config": QUIET_MEMORY,
    },
    "persona": {
        "vdb_config": {
            **PERSONA_TABLES,
            "host": "persona-vectors.internal",
            "port": 6334,
            "embedding": EMBEDDING,
        },
        "init_config": {name: {"enabled": False} for name in ("profiler", "speaker", "face")},
    },
    "tools": {"deepresearch": {"plugin": None}, "rag": {"plugin": None}, "mcp": MCP},
}
SELECTED = {
    "local": {
        "alphaavatar.memory.vdb.lancedb",
        "alphaavatar.persona.vdb.lancedb",
        "alphaavatar.persona.speaker.attribute",
        "alphaavatar.persona.speaker.vector",
        "alphaavatar.persona.face.analysis",
    },
    "remote": {
        "alphaavatar.memory.vdb.qdrant",
        "alphaavatar.persona.vdb.qdrant",
        "alphaavatar.mcp.vdb.lancedb",
    },
}


class Refused(Exception):
    pass


class RecordingExecutor(InferenceExecutor):
    """Offline transport double; method routing stays in the plugin code under test."""

    def __init__(self, responses: dict[str, bytes]) -> None:
        super().__init__("unused-test-endpoint")
        self.responses, self.calls = responses, []

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        self.calls.append((method, json.loads(data)["op"]))
        return self.responses[method]


class OfflineEmbeddings:
    def embed_query(self, text: str) -> list[float]:
        return [0.5] * 8

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


@pytest.fixture
def ambient() -> Iterator[dict[str, str]]:
    # Restored before the isolation guard compares the process environment.
    with mock.patch.dict(os.environ, {"MCP_TEST_TOKEN": "snapshot-token"}):
        try:
            yield os.environ
        finally:
            os.environ.pop(PLAN, None)


def relevant(methods: tuple[str, ...]) -> set[str]:
    prefixes = ("alphaavatar.memory.", "alphaavatar.persona.", "alphaavatar.mcp.")
    return {method for method in methods if method.startswith(prefixes)}


def avatar_runtime(root: Path, inference: InferenceExecutor, config: AvatarConfig) -> AvatarRuntime:
    workspace = WorkspacePaths.from_root(root)
    session = SessionRuntime(session_id="launch-session")
    return AvatarRuntime.create(
        workspace=workspace,
        session=session,
        session_path=workspace.data.sessions.get(session.session_id, date(2026, 11, 2)),
        state=StateRuntime(),
        config=config.runtime,
        inference=inference,
    )


def test_runner_launch_rejects_ambiguous_inputs_and_reconfiguration(tmp_path: Path) -> None:
    root, models = str(tmp_path / "workspace"), str(tmp_path / "models")
    for arguments in (("relative", models), (root, "relative"), (f"{root}/../escape", models)):
        with pytest.raises(ValueError, match="absolute"):
            RunnerLaunch(*arguments)
    with pytest.raises(ValueError, match="JSON object"):
        RunnerLaunch(root, models, config="[]")

    launch = RunnerLaunch(root, models, config=json.dumps({"memory": {"collection_name": "m"}}))
    runner = LaunchProbeRunner()
    with pytest.raises(RuntimeError, match="Configure RunnerLaunch"):
        runner.launch  # noqa: B018
    with pytest.raises(TypeError):
        runner.configure({"workspace_root": root, "models_dir": models})
    runner.configure(launch)
    runner.configure(RunnerLaunch(root, models, config=launch.config))
    with pytest.raises(RuntimeError, match="cannot change its workspace"):
        runner.configure(RunnerLaunch(str(tmp_path / "other"), models, config=launch.config))
    assert runner.launch == launch
    assert runner.config_for("memory") == {"collection_name": "m"}
    assert runner.config_for("persona") == {}
    runner = LaunchProbeRunner()
    runner.configure(RunnerLaunch(root, models, config='{"memory": []}'))
    with pytest.raises(ValueError, match="sections must be objects"):
        runner.config_for("memory")


async def test_in_process_and_spawned_runners_observe_the_same_launch(
    tmp_path: Path, ambient: os._Environ[str], socket_root: Path
) -> None:
    with mock.patch.dict(os.environ, {"QDRANT_URL": "https://snapshot-vectors.example"}):
        config = AvatarConfig.model_validate(
            REMOTE | {"memory": {"vdb_config": {"collection_name": "memories"}}}
        )
    launch = RunnerLaunch(
        str(tmp_path / "workspace"),
        str(tmp_path / "models"),
        config=snapshot_inference_config(config),
    )
    local = LaunchProbeRunner()
    local.configure(launch)
    local.initialize()

    # The child inherits a changed ambient endpoint; it must still use the frozen section.
    with mock.patch.dict(os.environ, {"QDRANT_URL": "https://ambient-vectors.example"}):
        expected = {name: json.loads(local.run(name.encode())) for name in ("memory", "persona")}
        runtime = InferenceRuntime(
            {LaunchProbeRunner.INFERENCE_METHOD: LaunchProbeRunner},
            mp_ctx=mp.get_context("spawn"),
            launch=launch,
            config=InferenceConfig(close_timeout=HANG_GUARD),
        )
        try:
            async with asyncio.timeout(HANG_GUARD):
                await runtime.start()
                spawned = {
                    name: json.loads(
                        await runtime.do_inference(
                            LaunchProbeRunner.INFERENCE_METHOD, name.encode()
                        )
                    )
                    for name in ("memory", "persona")
                }
        finally:
            async with asyncio.timeout(HANG_GUARD):
                await runtime.close()

    assert spawned == expected
    memory = spawned["memory"]
    assert (memory["workspace_root"], memory["models_dir"]) == (
        str(tmp_path / "workspace"),
        str(tmp_path / "models"),
    )
    assert memory["unchanged"] and memory["ambient_url"] == "https://ambient-vectors.example"
    assert memory["section"]["url"] == "https://snapshot-vectors.example"
    assert spawned["persona"]["section"]["host"] == "persona-vectors.internal"


@pytest.mark.parametrize("variant", ["local", "remote"])
def test_inference_plan_follows_the_configuration(variant: str, ambient: os._Environ[str]) -> None:
    config = AvatarConfig.model_validate(LOCAL if variant == "local" else REMOTE)
    methods = prepare_inference_runners(config)
    prepared = os.environ[PLAN]
    runners = bootstrap_inference_runners()

    assert relevant(methods) == SELECTED[variant]
    assert tuple(runners) == methods
    assert all(runner.INFERENCE_METHOD == method for method, runner in runners.items())
    # Registration accepts exactly the rebuilt plan, without starting any process.
    assert InferenceRuntime(runners).methods == methods
    assert prepare_inference_runners(config) == methods and os.environ[PLAN] == prepared


def test_inference_plan_refuses_conflicts_and_drifted_entries(
    ambient: os._Environ[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_inference_runners(AvatarConfig.model_validate(LOCAL))
    remote_qdrant_mcp = {**MCP, "vdb_config": {**MCP["vdb_config"], "url": "https://v.example"}}
    unsupported = AvatarConfig.model_validate(
        LOCAL | {"tools": {**LOCAL["tools"], "mcp": remote_qdrant_mcp}}
    )
    with pytest.raises(RuntimeError, match="alphaavatar.plugins.mcp") as failed:
        prepare_inference_runners(unsupported)
    assert "Unsupported MCP vector backend" in str(failed.value.__cause__)
    # A failed preparation leaves no plan from an earlier configuration behind.
    assert PLAN not in os.environ
    with pytest.raises(RuntimeError, match="Inference plan is missing"):
        bootstrap_inference_runners()

    with monkeypatch.context() as patch:
        patch.setitem(
            inference_bootstrap._runner_bootstraps,
            "test.launch",
            lambda config: (LaunchProbeRunner, LaunchProbeTwinRunner),
        )
        with pytest.raises(RuntimeError, match="test.launch") as failed:
            prepare_inference_runners(AvatarConfig.model_validate(LOCAL))
    assert "Conflicting inference runners" in str(failed.value.__cause__)

    entry = {"method": "test.launch_probe", "module": "launch_runner_samples"}
    for plan, error, match in (
        ([entry | {"name": "LaunchProbeRunner", "method": "test.renamed"}], ValueError, "changed"),
        (
            [entry | {"name": "LaunchProbeRunner", "module": "absent_runners"}],
            ImportError,
            "absent",
        ),
        ([entry | {"name": "Path", "module": "pathlib"}], TypeError, "InferenceRunner"),
        ([entry | {"name": "LaunchProbeRunner", "extra": "x"}], ValueError, "entry"),
    ):
        with mock.patch.dict(os.environ, {PLAN: json.dumps(plan)}):
            with pytest.raises(error, match=match):
                bootstrap_inference_runners()


@pytest.mark.parametrize("variant", ["local", "remote"])
async def test_plugin_factories_call_the_planned_runner_methods(
    variant: str, tmp_path: Path, ambient: os._Environ[str]
) -> None:
    config = AvatarConfig.model_validate(LOCAL if variant == "local" else REMOTE)
    methods = prepare_inference_runners(config)
    vdb = {
        name: [m for m in methods if m.startswith(f"alphaavatar.{name}.vdb.")]
        for name in ("memory", "persona", "mcp")
    }
    # Execution children rebuild plugins from the frozen values under another environment.
    with mock.patch.dict(os.environ, {"QDRANT_URL": "https://ambient-vectors.example"}):
        restored = AvatarConfig.model_validate(config.model_dump())
    assert len(vdb["memory"]) == len(vdb["persona"]) == 1
    responses = {
        vdb["memory"][0]: b'{"candidates": []}',
        vdb["persona"][0]: b'{"user_id": "speaker-user"}',
        **dict.fromkeys(vdb["mcp"], b'{"tools": [], "error": null}'),
    }
    executor = RecordingExecutor(responses)
    runtime = avatar_runtime(tmp_path / "workspace", executor, restored)
    try:
        memory = restored.memory.get_plugin(runtime=runtime, avatar_id="alphaavatar_demo")
        persona = restored.persona.get_plugin(runtime=runtime)
        tools = restored.tools.get_tools(runtime=runtime)
        recalled = await memory.store.recall_by_graph_node(
            owner_refs=[MemoryOwnerRef.avatar("alphaavatar_demo")],
            context=MemoryContextRef(episode_id="episode", context_id="context"),
            node_query="preferences",
        )
        speaker = await persona.store.search_speaker_vector(
            speaker_vector=np.zeros(4, dtype=np.float32), threshold=0.5
        )
        for tool in tools:
            await tool.on_start()
            try:
                await tool.invoke(MCPRequest(op=MCPOp.TOOL_SEARCH, query="calendar"))
            finally:
                await tool.on_stop()
    finally:
        await runtime.aclose()

    assert recalled == [] and speaker == "speaker-user"
    assert [method for method, _ in executor.calls] == vdb["memory"] + vdb["persona"] + vdb["mcp"]
    assert len(tools) == len(vdb["mcp"]) == (1 if variant == "remote" else 0)


def test_remote_vector_runners_connect_with_their_launch_snapshot(
    tmp_path: Path, ambient: os._Environ[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = {"QDRANT_URL": "https://snapshot-vectors.example", "QDRANT_API_KEY": "snapshot-key"}
    with mock.patch.dict(os.environ, snapshot):
        config = AvatarConfig.model_validate(
            REMOTE | {"memory": {"vdb_config": {"collection_name": "m", "embedding": EMBEDDING}}}
        )
    launch = RunnerLaunch(
        str(tmp_path / "workspace"),
        str(tmp_path / "models"),
        config=snapshot_inference_config(config),
    )
    connected: list[dict[str, object]] = []

    def connect(client: object, **kwargs: object) -> None:
        connected.append(kwargs)
        raise Refused  # Stop before any transport is opened.

    monkeypatch.setattr(qdrant_client.QdrantClient, "__init__", connect)
    ambient_values = {"QDRANT_URL": "https://ambient-vectors.example", "QDRANT_API_KEY": "ambient"}
    with mock.patch.dict(os.environ, ambient_values):
        for runner_cls in (memory_qdrant.QdrantRunner, persona_qdrant.QdrantRunner):
            runner = runner_cls()
            runner.configure(launch)
            with pytest.raises(Refused):
                runner.initialize()
            runner.close()

    memory, persona = connected
    assert memory == {
        "api_key": "snapshot-key",
        "url": "https://snapshot-vectors.example",
        "prefer_grpc": False,
    }
    assert (persona["url"], persona["host"], persona["port"], persona["api_key"]) == (
        None,
        "persona-vectors.internal",
        6334,
        "snapshot-key",
    )


def test_local_vector_runners_open_only_their_launch_workspace(
    tmp_path: Path, ambient: os._Environ[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = AvatarConfig.model_validate(LOCAL | {"tools": {**LOCAL["tools"], "mcp": MCP}})
    workspace = WorkspacePaths.from_root(tmp_path / "workspace")
    launch = RunnerLaunch(
        str(workspace.root), str(tmp_path / "models"), config=snapshot_inference_config(config)
    )
    providers: list[tuple[str, str, str]] = []

    def embeddings(task: object) -> OfflineEmbeddings:
        providers.append((task.kind.value, task.provider, task.model))
        return OfflineEmbeddings()

    def refuse_embeddings(task: object) -> OfflineEmbeddings:
        embeddings(task)
        raise Refused  # MCP would contact its servers next; this test stops at local inputs.

    monkeypatch.setattr(memory_lancedb, "create_embedding_model", embeddings)
    monkeypatch.setattr(persona_lancedb, "create_embedding_model", embeddings)
    monkeypatch.setattr(mcp_lancedb, "create_embedding_model", refuse_embeddings)
    ambient_values = {"QDRANT_URL": "https://ambient-vectors.example", "MCP_TEST_TOKEN": "changed"}
    with mock.patch.dict(os.environ, ambient_values):
        for runner_cls in (memory_lancedb.LanceDBRunner, persona_lancedb.LanceDBRunner):
            runner = runner_cls()
            runner.configure(launch)
            runner.initialize()
            runner.close()
        mcp = mcp_lancedb.LanceDBRunner()
        mcp.configure(launch)
        with pytest.raises(Refused):
            mcp.initialize()
        servers = mcp._servers
        mcp.close()

    indexes = workspace.data.indexes
    tables = {
        name: sorted(
            path.name for path in indexes.namespace(name).backend("lancedb").root.iterdir()
        )
        for name in ("memory", "persona", "mcp")
    }
    assert sorted(path.name for path in tmp_path.iterdir()) == ["home", "tmp", "workspace"]
    assert tables == {
        "memory": ["memories.lance"],
        "persona": ["faces.lance", "profiles.lance", "speakers.lance"],
        "mcp": [],
    }
    assert providers == [("embedding", "openai", "text-embedding-3-small")] * 3
    assert servers["docs"]["headers"] == {"Authorization": "Bearer snapshot-token"}
