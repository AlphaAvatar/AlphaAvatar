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
"""Resource checks shared by the inference tests: child processes, descriptors, sockets."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
from collections import Counter
from collections.abc import Callable
from multiprocessing import resource_tracker
from pathlib import Path

import pytest

from alphaavatar.agents.runtime.inference import INFERENCE_SOCKET_ENV

HANG_GUARD = 30


def children() -> set[int]:
    return {process.pid for process in mp.active_children()}


def descriptors() -> Counter[str] | None:
    """This process's descriptor targets, or None where /proc is unavailable."""
    directory = Path("/proc/self/fd")
    if not directory.is_dir():
        return None
    resource_tracker.ensure_running()  # Process-wide stdlib facility, not runner-owned.
    # Count per target: two leaked descriptors may share one target such as a pipe.
    targets: Counter[str] = Counter()
    for entry in directory.iterdir():
        try:
            targets[os.readlink(entry)] += 1
        except FileNotFoundError:
            pass  # The descriptor used to list the directory has already closed.
    return targets


def assert_released(socket_root: Path, before: set[int], fds: Counter[str] | None) -> None:
    assert children() - before == set()
    assert INFERENCE_SOCKET_ENV not in os.environ
    assert list(socket_root.iterdir()) == []
    after = descriptors()
    if fds is not None and after is not None:
        assert after - fds == Counter()


def settled(caplog: pytest.LogCaptureFixture, method: str) -> tuple[int | None, bool]:
    """Exit code and forced flag from the runner's own reclamation diagnostic."""
    (record,) = [
        record
        for record in caplog.records
        if record.getMessage().startswith(f"Inference process settled method={method} ")
    ]
    return record.args[2], record.args[3]


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.002)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)
