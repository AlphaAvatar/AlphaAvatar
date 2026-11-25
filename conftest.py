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

import _socket
import argparse
import asyncio
import inspect
import math
import multiprocessing
import os
import re
import shutil
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
_LOOPBACK = frozenset({"127.0.0.1", "::1"})


def _stress_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError("must be a finite, nonnegative number of seconds")
    return seconds


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--stress-seconds",
        type=_stress_seconds,
        default=0.0,
        help="Run each synthetic stress test for this long; 0 runs one bounded round.",
    )


def pytest_configure(config: pytest.Config) -> None:
    # pytest-asyncio asks for the current loop before each async test. With none ever set,
    # asyncio would create one there that nothing closes; with "none" set, it creates none.
    asyncio.set_event_loop(None)


@pytest.fixture
def stress_seconds(request: pytest.FixtureRequest) -> float:
    return request.config.getoption("stress_seconds")


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


def _local_address(address: object) -> bool:
    if type(address) is str:
        return os.path.isabs(address) and "\0" not in address
    return (
        type(address) is tuple
        and len(address) == 2
        and address[0] in _LOOPBACK
        and type(address[1]) is int
        and 0 < address[1] < 65536
    )


class _OwnedAddresses(set):
    """Absolute AF_UNIX paths or numeric loopback (host, port) pairs the test serves itself."""

    def add(self, address: object) -> None:
        if not _local_address(address):
            raise TypeError("Own only absolute AF_UNIX paths or numeric loopback (host, port)")
        super().add(address)

    def allows(self, sock: socket.socket, address: object) -> bool:
        # Revalidate at the boundary: set operators such as ^= insert without add().
        if sock.family == socket.AF_UNIX and type(address) is str:
            key = address
        elif sock.family in (socket.AF_INET, socket.AF_INET6) and type(address) is tuple:
            key = address[:2]
        else:
            return False
        return _local_address(key) and key in self


@pytest.fixture
def owned_addresses(network_denied: None, monkeypatch: pytest.MonkeyPatch) -> set[object]:
    """Opt-in: reach only the AF_UNIX paths or loopback addresses this test registers."""
    addresses = _OwnedAddresses()
    refuse_connect, refuse_sendto = socket.socket.connect, socket.socket.sendto

    def connect(sock: socket.socket, address: object) -> None:
        if addresses.allows(sock, address):
            return _socket.socket.connect(sock, address)
        return refuse_connect(sock, address)

    def sendto(sock: socket.socket, data: bytes, *args: object) -> int:
        if args and addresses.allows(sock, args[-1]):
            return _socket.socket.sendto(sock, data, *args)
        return refuse_sendto(sock, data, *args)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "sendto", sendto)
    return addresses


@pytest.fixture
def socket_root(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Give a runtime its own short temp root and prove it removes its socket directory."""
    root = Path(tempfile.mkdtemp(prefix="aa-", dir="/tmp"))
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    yield root
    leftovers = sorted(path.name for path in root.iterdir())
    shutil.rmtree(root)
    assert leftovers == [], "the runtime left its socket directory behind"


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
