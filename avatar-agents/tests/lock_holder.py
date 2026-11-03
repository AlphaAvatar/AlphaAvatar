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
"""Hold a shared directory lock in another interpreter until a test opens its gate."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

HANG_GUARD = 30
_HOLDER = """
import pathlib, sys, time
from alphaavatar.agents.utils.files.atomic import locked_directory
directory, ready, gate = map(pathlib.Path, sys.argv[1:])
with locked_directory(directory):
    ready.touch()
    deadline = time.monotonic() + 60
    while not gate.exists():
        if time.monotonic() > deadline:
            sys.exit(3)
        time.sleep(0.005)
"""


@contextmanager
def held_elsewhere(directory: Path, scratch: Path) -> Iterator[Path]:
    """Yield the gate file; the other process holds the lock until it exists."""
    ready, gate = scratch / f"{directory.name}.held", scratch / f"{directory.name}.release"
    process = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(directory), str(ready), str(gate)]
    )
    try:
        deadline = time.monotonic() + HANG_GUARD
        while not ready.exists():
            assert process.poll() is None, "The holder exited before locking"
            assert time.monotonic() < deadline, "The holder never locked"
            time.sleep(0.005)
        yield gate
    finally:
        gate.touch()
        try:
            assert process.wait(HANG_GUARD) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
