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
"""Default Host endpoints stay private and within the AF_UNIX bound under any temp root."""

from __future__ import annotations

import asyncio
import errno
import io
import json
import logging
import multiprocessing as mp
import os
import socket
import stat
import tempfile
from pathlib import Path

import pytest
from inference_runner_samples import EchoRunner

from alphaavatar.agents.configs.runtime_config import InferenceConfig
from alphaavatar.agents.runtime.inference import InferenceExecutor, InferenceRuntime
from alphaavatar.core.ipc import MAX_SOCKET_PATH
from alphaavatar.core.log.records import LOG_ENDPOINT_ENV
from alphaavatar.host.log.runtime import HostLog

HANG_GUARD = 30
ECHO = EchoRunner.INFERENCE_METHOD


@pytest.fixture(params=["short", "long"])
def temp_root(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Path, Path]:
    """Return the configured temp root and where the endpoint directory must be created."""
    if request.param == "short":
        root = request.getfixturevalue("socket_root")
        return root, root
    # A valid but long TMPDIR, as on CI runners or app sandboxes, cannot hold the socket path.
    root = tmp_path / ("t" * 90)
    root.mkdir()
    request.getfixturevalue("monkeypatch").setattr(tempfile, "tempdir", str(root))
    return root, Path("/tmp")


def assert_private(endpoint: str, parent: Path) -> None:
    directory = Path(endpoint).parent
    assert len(os.fsencode(endpoint)) <= MAX_SOCKET_PATH
    assert directory.parent == parent
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


async def test_inference_endpoint_fits_and_is_released(
    temp_root: tuple[Path, Path], owned_endpoints: set[object]
) -> None:
    root, parent = temp_root
    runtime = InferenceRuntime(
        {ECHO: EchoRunner},
        mp_ctx=mp.get_context("spawn"),
        config=InferenceConfig(initialize_timeout=HANG_GUARD),
    )
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        endpoint = runtime.endpoint
        assert_private(endpoint, parent)
        owned_endpoints.add(endpoint)
        executor = InferenceExecutor(endpoint)
        try:
            assert await executor.do_inference(ECHO, b"probe") == b"probe"
        finally:
            await executor.close()
    finally:
        await runtime.close()
    assert not Path(endpoint).parent.exists()
    assert list(root.iterdir()) == []


def test_host_log_endpoint_fits_and_is_released(
    temp_root: tuple[Path, Path], owned_endpoints: set[object]
) -> None:
    root, parent = temp_root
    stream = io.StringIO()
    logs = HostLog(devmode=False, stream=stream)
    try:
        endpoint = json.loads(os.environ[LOG_ENDPOINT_ENV])["path"]
        assert_private(endpoint, parent)
        owned_endpoints.add(endpoint)
        logging.getLogger("alphaavatar.test").warning("endpoint probe")
    finally:
        logs.close()
    assert "endpoint probe" in stream.getvalue()
    assert not Path(endpoint).parent.exists()
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("refused", [1, 2], ids=["receiver", "client"])
def test_host_log_construction_failure_releases_its_directory(
    refused: int, socket_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created, handlers = [], list(logging.root.handlers)
    real = socket.socket

    def sandboxed(family: int = -1, *args: object, **kwargs: object) -> socket.socket:
        # A sandbox may refuse local sockets with EPERM, as some review hosts do.
        if family == socket.AF_UNIX:
            created.append(family)
            if len(created) == refused:
                raise PermissionError(errno.EPERM, "Operation not permitted")
        return real(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", sandboxed)
    with pytest.raises(PermissionError):
        HostLog(devmode=False, stream=io.StringIO())
    assert len(created) == refused
    assert list(socket_root.iterdir()) == []
    assert LOG_ENDPOINT_ENV not in os.environ
    assert logging.root.handlers == handlers
