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
"""Health endpoints stay local by default and report operational state, never configuration."""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
from dataclasses import fields
from pathlib import Path
from unittest import mock

import pytest
from inference_runner_samples import EchoRunner

# Imported at collection: configuration plugins adjust process variables while importing.
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.agents.runtime.inference import InferenceRuntime
from alphaavatar.host.application.application import AvatarHost
from alphaavatar.host.application.health import HealthServer
from alphaavatar.host.configs.loader import restore_application, validate_application
from alphaavatar.host.execution.schemas import ExecutionView

HANG_GUARD = 30
SECRETS = {
    "LIVEKIT_API_KEY": "fictional-livekit-key-0042",
    "LIVEKIT_API_SECRET": "fictional-livekit-secret-0042",
    "vdb": "fictional-vdb-api-key-0042",
    "mcp": "fictional-mcp-token-0042",
}
STATUS = {
    "ready",
    "inference_ready",
    "session_backend_ready",
    "active_executions",
    "admission_available",
    "recent_executions",
    "inference_runners",
    "inference_methods",
}
RUNNER = {"method", "startup_state", "ready", "startup_elapsed_seconds", "error_type"}
EXECUTION = {"execution_id", "backend", "source_id", "state", "reason", "pid", "stop_reason"}


def application(root: Path, health: dict[str, object] | None = None):
    return validate_application(
        {
            "application": {"home": str(root / "application")},
            "avatar": {"id": "health"},
            "memory": {"vdb_config": {"url": "https://vectors.invalid", "api_key": SECRETS["vdb"]}},
            "tools": {
                "mcp": {
                    "enabled": True,
                    "servers": {
                        "docs": {
                            "url": "https://mcp.invalid/mcp",
                            "headers": {"Authorization": f"Bearer {SECRETS['mcp']}"},
                        }
                    },
                }
            },
            "host": {"health": health or {}},
        }
    )


async def get(port: int, path: str) -> tuple[int, bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(f"GET {path} HTTP/1.1\r\nHost: local\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        response = await reader.read()
    finally:
        writer.close()
        await writer.wait_closed()
    head, _, body = response.partition(b"\r\n\r\n")
    return int(head.split()[1]), body


@pytest.mark.parametrize(
    ("health", "bind"),
    [({}, "127.0.0.1"), ({"bind": "0.0.0.0"}, "0.0.0.0")],
    ids=["default", "explicit-external"],
)
async def test_health_listens_locally_unless_a_bind_is_configured(
    health: dict[str, object], bind: str, tmp_path: Path
) -> None:
    config = application(tmp_path, {**health, "port": 0})
    assert restore_application(config.payload).host.health.bind == bind
    server = HealthServer(config.host.health, devmode=True, ready=lambda: True, status=dict)
    try:
        await server.on_start()
        # Read-only: the address the aiohttp site actually bound.
        assert server._runner.addresses[0][0] == bind
    finally:
        await server.on_stop()


async def test_status_reports_operational_state_without_configuration(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    config = application(tmp_path, {"port": 0})
    credentials = {key: value for key, value in SECRETS.items() if key.startswith("LIVEKIT")}
    with mock.patch.dict(os.environ, {"LIVEKIT_URL": "wss://livekit.invalid", **credentials}):
        host = AvatarHost(config, devmode=True)
    runtime = InferenceRuntime(
        {EchoRunner.INFERENCE_METHOD: EchoRunner}, mp_ctx=mp.get_context("spawn")
    )
    server = HealthServer(
        config.host.health, devmode=True, ready=lambda: host.ready, status=host.status
    )
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        host._inference = runtime  # The Host owns this slot once its runtime is serving.
        await server.on_start()
        owned_endpoints.add(("127.0.0.1", server.port))
        code, body = await get(server.port, "/status")
    finally:
        await server.on_stop()
        await runtime.close()

    status = json.loads(body)
    assert code == 200 and status.keys() == STATUS
    assert [runner.keys() for runner in status["inference_runners"]] == [RUNNER]
    assert status["inference_methods"] == [EchoRunner.INFERENCE_METHOD]
    # Execution views publish these fields only: ids, codes and a pid, never configuration.
    assert {field.name for field in fields(ExecutionView)} == EXECUTION
    text = body.decode()
    assert [name for name, secret in SECRETS.items() if secret in text] == []
    assert str(tmp_path) not in text and "vectors.invalid" not in text
