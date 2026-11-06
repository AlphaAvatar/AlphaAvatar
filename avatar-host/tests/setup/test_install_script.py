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
"""install.sh with a package of its layout: what it checks is what it unpacks and runs, and a
current it cannot tell it made is left as it is."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "packaging/linux/install.sh"
ID = "9.9.9-test"
LAUNCHER = '#!/bin/sh\n{effect}[ "$1" = --version ] && echo "AlphaAvatar 9.9.9"\nexit 0\n'

pytestmark = pytest.mark.skipif(
    (platform.system(), platform.machine()) != ("Linux", "x86_64"),
    reason="install.sh installs the Linux x86_64 package",
)


def package(directory: Path, effect: str = "") -> Path:
    """A base package as install.sh reads one: one top directory, its manifest, its command."""
    top = directory / f"alphaavatar-{ID}"
    manifest = {"id": ID, "version": "9.9.9", "glibc": "2.17", "cpu": [], "imports": ["json"]}
    (top / "share/alphaavatar").mkdir(parents=True)
    (top / "share/alphaavatar/manifest.json").write_text(json.dumps(manifest))
    (top / "python/bin").mkdir(parents=True)
    (top / "python/bin/python3").symlink_to(sys._base_executable)
    (top / "bin").mkdir()
    (top / "bin/alphaavatar").write_text(LAUNCHER.format(effect=effect))
    (top / "bin/alphaavatar").chmod(0o755)
    archive = directory / f"alphaavatar-{ID}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(top, arcname=top.name)
    shutil.rmtree(top)
    return archive


@pytest.fixture
def layout(tmp_path: Path):
    good = package(tmp_path / "good")
    digest = hashlib.sha256(good.read_bytes()).hexdigest()
    home, tools = tmp_path / "home", tmp_path / "tools"
    home.mkdir(exist_ok=True)
    tools.mkdir()
    env = {"HOME": str(home), "PATH": f"{tools}:{os.environ['PATH']}", "LANG": "C.UTF-8"}

    def run(*argv: str, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        command = ["bash", str(SCRIPT), "--file", str(good), "--sha256", digest]
        command += ["--prefix", str(tmp_path / "prefix"), "--bin-dir", str(tmp_path / "bin")]
        return subprocess.run(
            [*command, *argv],
            capture_output=True,
            text=True,
            timeout=120,
            env=env | (extra or {}),
            cwd="/",
        )

    return tmp_path, good, tools, run


def test_the_package_checked_is_the_one_unpacked_whatever_replaces_the_source(layout) -> None:
    tmp_path, good, tools, run = layout
    # Another package, its command marking that it ran, takes the source's place once a
    # SHA-256 is computed: the moment after install.sh checked it.
    replacement = package(tmp_path / "other", effect=f": > {tmp_path / 'replacement-ran'}\n")
    real = shutil.which("sha256sum")
    (tools / "sha256sum").write_text(
        f'#!/bin/sh\n"{real}" "$@"\nstatus=$?\ncp "{replacement}" "{good}"\nexit $status\n'
    )
    (tools / "sha256sum").chmod(0o755)
    installed = run()
    assert installed.returncode == 0, installed.stderr
    command = tmp_path / "prefix/versions" / ID / "bin/alphaavatar"
    assert "replacement-ran" not in command.read_text()
    assert not (tmp_path / "replacement-ran").exists()
    assert os.readlink(tmp_path / "prefix/current") == f"versions/{ID}"


@pytest.mark.parametrize("current", ["linked version", "unmarked environment", "linked versions"])
def test_a_current_this_script_cannot_tell_it_made_is_left_as_it_is(layout, current: str) -> None:
    tmp_path, _, _, run = layout
    prefix, outside = tmp_path / "prefix", tmp_path / "outside"
    (outside / "share/alphaavatar").mkdir(parents=True)
    (outside / "kept").write_text("someone's")
    if current == "linked versions":  # A first installation would unpack through it.
        prefix.mkdir()
        (prefix / "versions").symlink_to(outside)
    elif current == "linked version":
        (prefix / "versions").mkdir(parents=True)
        (prefix / "versions/base").symlink_to(outside)
        (prefix / "current").symlink_to("versions/base")
    else:
        (prefix / "envs/plan").mkdir(parents=True)  # Not setup's: it carries no mark.
        (prefix / "current").symlink_to("envs/plan")
    link = os.readlink(prefix / "current") if (prefix / "current").is_symlink() else None
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    refused = run()
    assert refused.returncode == 1
    assert "it is left as it is" in refused.stderr
    assert (os.readlink(prefix / "current") if link else None) == link
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    # The lock file the run took is all it adds; nothing else is made, moved or removed.
    assert [path for path in after if path not in before] == ["prefix/.install.lock"]
    assert (outside / "kept").read_text() == "someone's"


def test_the_lock_is_never_opened_through_a_link_or_pipe_nor_truncated(layout) -> None:
    tmp_path, _, _, run = layout
    prefix, outside = tmp_path / "prefix", tmp_path / "outside-file"
    outside.write_text("someone's data\n")
    prefix.mkdir()
    (prefix / ".install.lock").symlink_to(outside)
    refused = run()
    assert refused.returncode == 1 and "is not a lock file" in refused.stderr
    assert outside.read_text() == "someone's data\n"
    assert os.readlink(prefix / ".install.lock") == str(outside)
    # A pipe in its place, which opening for writing would wait on, is refused too.
    (prefix / ".install.lock").unlink()
    os.mkfifo(prefix / ".install.lock")
    refused = run()
    assert refused.returncode == 1 and "is not a lock file" in refused.stderr
    assert stat.S_ISFIFO((prefix / ".install.lock").lstat().st_mode)
    # A lock file already there keeps what it holds: opening it truncates nothing.
    (prefix / ".install.lock").unlink()
    (prefix / ".install.lock").write_text("held\n")
    installed = run()
    assert installed.returncode == 0, installed.stderr
    assert (prefix / ".install.lock").read_text() == "held\n"


def test_a_failed_first_installation_keeps_the_lock_every_run_takes(layout) -> None:
    tmp_path, _, _, run = layout
    failed = run("--sha256", "0" * 64)
    assert failed.returncode == 1 and "does not match its SHA-256" in failed.stderr
    # The prefix it made holds the lock alone. Removed, a run that had opened it already would
    # lock the old file, the next a new one beside it, and both would install at once.
    assert [path.name for path in (tmp_path / "prefix").iterdir()] == [".install.lock"]
    assert not (tmp_path / "bin/alphaavatar").exists()
