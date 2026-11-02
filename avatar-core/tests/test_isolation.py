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
"""The shared harness rejects ambiguous stress budgets and endpoints a test does not own."""

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
    "address",
    [
        "relative.sock",
        b"/tmp/bytes.sock",
        "\0abstract",
        ("10.0.0.1", 443),
        ("localhost", 443),
        ("127.0.0.1", 0),
        ("127.0.0.1", "443"),
        ("127.0.0.1", 443, 0, 0),
    ],
)
def test_owned_endpoints_accept_only_local_addresses(
    address: object, owned_endpoints: set[object]
) -> None:
    with pytest.raises(TypeError):
        owned_endpoints.add(address)
    with pytest.raises(TypeError):
        owned_endpoints |= {address}
    assert not owned_endpoints


def test_owned_unix_endpoint_is_reachable(socket_root: Path, owned_endpoints: set[object]) -> None:
    path = str(socket_root / "owned.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen()
        owned_endpoints.add(path)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(path)
            accepted, _ = server.accept()
            accepted.close()
    os.unlink(path)
