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
"""Host test fixtures: no service client, local socket or ambient credential."""

from __future__ import annotations

import errno
import os
import socket
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import lancedb
import large_samples
import pytest
import qdrant_client
from config_samples import SECRETS


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Refuse service clients and local sockets, as a restricted review host would."""
    refused: list[str] = []
    real = socket.socket

    def record(name: str):
        def refuse(*args: object, **kwargs: object) -> None:
            refused.append(name)
            raise AssertionError(f"{name} constructed by a configuration command")

        return refuse

    def local_socket(family: int = -1, *args: object, **kwargs: object) -> socket.socket:
        if family == socket.AF_UNIX:
            refused.append("AF_UNIX")
            raise PermissionError(errno.EPERM, "Operation not permitted")
        return real(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", local_socket)
    monkeypatch.setattr(qdrant_client.QdrantClient, "__init__", record("QdrantClient"))
    monkeypatch.setattr(qdrant_client.AsyncQdrantClient, "__init__", record("AsyncQdrantClient"))
    monkeypatch.setattr(lancedb, "connect", record("lancedb.connect"))
    return refused


@pytest.fixture
def home(tmp_path: Path) -> Iterator[Path]:
    """An application home of the test's own, chosen as users choose one."""
    root = tmp_path / "application"
    with mock.patch.dict(os.environ, {"ALPHAAVATAR_HOME": str(root)}):
        yield root


@pytest.fixture
def credentials() -> object:
    # Restored before the isolation guard compares the process environment.
    with mock.patch.dict(os.environ, {k: v for k, v in SECRETS.items() if k.isupper()}):
        yield


@pytest.fixture(scope="session")
def large_sample_files(request: pytest.FixtureRequest) -> dict[str, Path]:
    """Every large sample the selected tests name, fetched once, before any test's guards."""
    names = sorted(
        {
            name
            for item in request.session.items
            for marker in item.iter_markers("large_samples")
            for name in marker.args
        }
    )
    found, failures = {}, []
    for name in names:
        try:
            found[name] = large_samples.fetch(name)
        except large_samples.LargeSampleError as error:
            failures.append(str(error))
    if failures:
        pytest.fail("Large samples unavailable:\n" + "\n".join(failures), pytrace=False)
    return found


@pytest.fixture
def large_sample(large_sample_files: dict[str, Path]):
    """The local file of a large sample this test's ``large_samples`` marker names."""
    return large_sample_files.__getitem__
