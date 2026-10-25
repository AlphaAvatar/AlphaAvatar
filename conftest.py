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
"""Deterministic test isolation shared by every workspace package.

Guards compare against the state captured before the current test and act only on the
difference; resources that already existed belong to someone else and are never touched.
The network guard patches this interpreter only: spawned children do not inherit it.
"""

from __future__ import annotations

import asyncio
import inspect
import multiprocessing
import os
import re
import socket
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

# Credentials, deployment selectors, model caches and proxies must not leak in from the shell.
_SCRUBBED = re.compile(
    r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL"
    r"|^(AVATAR_|ALPHAAVATAR_|MEMORY_|PERSONA_|MCP_|LIVEKIT_|OPENAI_|ANTHROPIC_|TAVILY_|"
    r"QDRANT_|VOICEAI_|HF_|HUGGINGFACE_|TRANSFORMERS_|SILERO_|SMART_TURN_|AIRI_|XDG_)"
    r"|^(ENV_FILE|FORCE_CPU|CUDA_VISIBLE_DEVICES|HTTPS?_PROXY|ALL_PROXY|NO_PROXY)$",
    re.IGNORECASE,
)
_IGNORED_ENVIRONMENT = frozenset({"PYTEST_CURRENT_TEST"})


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for name in tuple(os.environ):
        if _SCRUBBED.search(name):
            monkeypatch.delenv(name)
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()
    for name, value in {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "ENV_FILE": str(tmp_path / "absent.env"),
        "HF_HOME": str(home / ".cache" / "huggingface"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "ALPHAAVATAR_MODEL_OFFLINE": "1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    monkeypatch.chdir(tmp_path)

    expected = dict(os.environ)
    yield tmp_path
    changed = sorted(
        name
        for name in expected.keys() | os.environ.keys()
        if name not in _IGNORED_ENVIRONMENT and expected.get(name) != os.environ.get(name)
    )
    for name in changed:
        if name in expected:
            os.environ[name] = expected[name]
        else:
            del os.environ[name]
    if changed:
        # Report names only: values may be credentials.
        pytest.fail(f"Test changed process environment variables: {changed}", pytrace=False)


@pytest.fixture(autouse=True)
def network_denied(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Refuse every outbound connection or lookup; socketpair() stays available."""
    attempts: list[str] = []

    def deny(operation: str):
        def refuse(*args: object, **kwargs: object) -> object:
            attempts.append(operation)
            raise PermissionError(f"Deterministic tests may not use the network: {operation}")

        return refuse

    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, deny(f"socket.{name}"))
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "create_connection"):
        monkeypatch.setattr(socket, name, deny(f"socket.{name}"))
    yield
    if attempts:
        # Fail even when the code under test swallowed the refusal.
        pytest.fail(f"Test attempted network access: {sorted(set(attempts))}", pytrace=False)


@pytest.fixture(autouse=True)
def owned_child_processes() -> Iterator[None]:
    before = {process.pid for process in multiprocessing.active_children()}
    yield
    leaked = [process for process in multiprocessing.active_children() if process.pid not in before]
    for process in leaked:
        process.kill()
        process.join(5)
    if leaked:
        names = sorted(process.name for process in leaked)
        pytest.fail(f"Test leaked child processes: {names}", pytrace=False)


@pytest.fixture
async def owned_tasks() -> AsyncIterator[None]:
    before = asyncio.all_tasks()
    yield
    for _ in range(3):
        await asyncio.sleep(0)
    current = asyncio.current_task()
    leaked = [task for task in asyncio.all_tasks() - before - {current} if not task.done()]
    for task in leaked:
        task.cancel()
    await asyncio.gather(*leaked, return_exceptions=True)
    if leaked:
        names = sorted(task.get_name() for task in leaked)
        pytest.fail(f"Test leaked asyncio tasks: {names}", pytrace=False)


@pytest.fixture(autouse=True)
def _guard_async_tasks(request: pytest.FixtureRequest) -> None:
    if inspect.iscoroutinefunction(request.function):
        request.getfixturevalue("owned_tasks")
