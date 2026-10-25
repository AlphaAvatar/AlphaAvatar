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
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Base CLI commands must not need models, providers, transports or avatar configuration.
FORBIDDEN_IMPORTS = (
    "torch",
    "numpy",
    "openai",
    "qdrant_client",
    "llama_cpp",
    "livekit",
    "omegaconf",
    "alphaavatar.plugins",
    "alphaavatar.agents.configs",
)
IMPORT_PROBE = """
import contextlib, io, json, sys
from alphaavatar.host.cli.app import main
for argv in (["--help"], ["--version"]):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.suppress(SystemExit):
        main(argv)
forbidden = tuple(sys.argv[1:])
print(json.dumps(sorted(
    name for name in sys.modules if any(name == f or name.startswith(f + ".") for f in forbidden)
)))
"""


def files_under(root: Path) -> list[Path]:
    return sorted(path.relative_to(root) for path in root.rglob("*"))


def test_base_cli_needs_no_models_credentials_or_workspace(tmp_path: Path) -> None:
    entrypoint = Path(sys.executable).with_name("alphaavatar")
    assert entrypoint.is_file(), f"Console script is not installed beside {sys.executable}"
    before = files_under(tmp_path)
    for argv in (["--help"], ["--version"]):
        completed = subprocess.run(
            [str(entrypoint), *argv], capture_output=True, text=True, timeout=60, env=os.environ
        )
        assert completed.returncode == 0, completed.stderr

    probe = subprocess.run(
        [sys.executable, "-c", IMPORT_PROBE, *FORBIDDEN_IMPORTS],
        capture_output=True,
        text=True,
        timeout=60,
        env=os.environ,
    )
    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout.splitlines()[-1]) == []
    assert files_under(tmp_path) == before
