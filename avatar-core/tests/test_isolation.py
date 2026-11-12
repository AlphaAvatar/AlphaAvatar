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
"""The shared harness rejects ambiguous stress budgets and addresses a test does not own."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("value", "code"),
    [("-1", 4), ("nan", 4), ("inf", 4), ("0.25", 0)],
    ids=["negative", "nan", "infinite", "finite"],
)
def test_stress_budget_must_be_finite_and_nonnegative(value: str, code: int) -> None:
    target = ROOT / "avatar-core" / "tests" / "test_lifecycle.py"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--co", "-q"]
        + [f"--stress-seconds={value}", str(target)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == code, result.stderr
    assert ("--stress-seconds" in result.stderr) == bool(code)


@pytest.mark.parametrize(
    ("family", "address"),
    [
        (socket.AF_UNIX, "relative.sock"),
        (socket.AF_UNIX, b"/tmp/bytes.sock"),
        (socket.AF_UNIX, "\0abstract"),
        (socket.AF_INET, ("10.0.0.1", 443)),
        (socket.AF_INET, ("localhost", 443)),
        (socket.AF_INET, ("127.0.0.1", 0)),
        (socket.AF_INET, ("127.0.0.1", "443")),
        (socket.AF_INET6, ("::1", 443, 0, 0)),
    ],
)
def test_owned_addresses_accept_only_local_ones(
    family: int, address: object, owned_addresses: set[object]
) -> None:
    with pytest.raises(TypeError):
        owned_addresses.add(address)
    # Set operators bypass add(); the connect/sendto boundary must still refuse the address.
    owned_addresses ^= {address}
    owned_addresses.symmetric_difference_update({("192.0.2.1", 80)})
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        assert not owned_addresses.allows(sock, address)
        if family != socket.AF_UNIX:
            assert not owned_addresses.allows(sock, ("192.0.2.1", 80))


def test_owned_unix_socket_is_reachable(socket_root: Path, owned_addresses: set[object]) -> None:
    path = str(socket_root / "owned.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen()
        owned_addresses.add(path)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(path)
            accepted, _ = server.accept()
            accepted.close()
    os.unlink(path)
