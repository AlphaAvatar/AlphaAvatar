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
"""install.sh with a package of its layout: what it checks is what it unpacks and runs, a
current it cannot tell it made is left as it is, and a stopped run leaves current, the command
and the data as they were, and nothing the next run does not remove."""

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
ID, OTHER = "9.9.9-test", "9.9.9-other"
LAUNCHER = '#!/bin/sh\n{effect}[ "$1" = --version ] && echo "AlphaAvatar 9.9.9"\nexit 0\n'

pytestmark = pytest.mark.skipif(
    (platform.system(), platform.machine()) != ("Linux", "x86_64"),
    reason="install.sh installs the Linux x86_64 package",
)


def package(directory: Path, effect: str = "", package_id: str = ID) -> Path:
    """A base package as install.sh reads one: one top directory, its manifest, its command."""
    top = directory / f"alphaavatar-{package_id}"
    manifest = {
        "id": package_id,
        "version": "9.9.9",
        "glibc": "2.17",
        "cpu": [],
        "imports": ["json"],
    }
    (top / "share/alphaavatar").mkdir(parents=True)
    (top / "share/alphaavatar/manifest.json").write_text(json.dumps(manifest))
    (top / "python/bin").mkdir(parents=True)
    (top / "python/bin/python3").symlink_to(sys._base_executable)
    (top / "bin").mkdir()
    (top / "bin/alphaavatar").write_text(LAUNCHER.format(effect=effect))
    (top / "bin/alphaavatar").chmod(0o755)
    archive = directory / f"alphaavatar-{package_id}.tar.gz"
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
            start_new_session=True,  # Its own process group, as a terminal's job is.
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


# A command on PATH in place of the real one; where its arguments hold $INJECT_AT, the run is
# sent $INJECT_SIGNAL before the command acts or after ($INJECT_WHEN): the script alone, as
# kill sends it, or its whole process group, as a terminal sends Ctrl-C and hangups.
SIGNALLING = """#!/bin/sh
case "$*" in *"$INJECT_AT"*) hit=1 ;; *) hit="" ;; esac
to=0
[ "$INJECT_TO" = group ] || to=$(cut -d' ' -f5 /proc/$$/stat)
if [ -n "$hit" ] && [ "$INJECT_WHEN" = before ]; then kill -s "$INJECT_SIGNAL" "$to"; sleep 0.5; fi
"{real}" "$@"
status=$?
if [ -n "$hit" ] && [ "$INJECT_WHEN" = after ]; then kill -s "$INJECT_SIGNAL" "$to"; fi
exit $status
"""


def signalling(tools: Path, command: str) -> None:
    (tools / command).write_text(SIGNALLING.replace("{real}", shutil.which(command)))
    (tools / command).chmod(0o755)


def runs(entry: Path) -> str:
    return subprocess.run([entry, "--version"], capture_output=True, text=True, cwd="/").stdout


@pytest.mark.parametrize(
    ("step", "signal", "when"),
    [
        # The moment after the step acted, before the run records it.
        *(
            (step, signal, "after")
            for step in ("stage", "version", "switch")
            for signal in ("TERM", "INT", "HUP")
        ),
        # While it acts: the run waits for it.
        *((step, "TERM", "before") for step in ("stage", "version", "switch")),
    ],
)
def test_a_signal_as_a_step_makes_something_acts_once_it_is_recorded(
    layout, step: str, signal: str, when: str
) -> None:
    """A signal as the stage appears, as the version moves into versions/, or as current
    switches, the moment after or while it acts: the step completes and is recorded, then the
    run ends, as the signal would have.
    Current is the version it was, unless the switch completed; the command runs; the data are
    untouched; nothing of the run is left; the retry installs."""
    tmp_path, _, tools, run = layout
    prefix, entry, data = tmp_path / "prefix", tmp_path / "bin/alphaavatar", tmp_path / "data"
    other = package(tmp_path / "next", package_id=OTHER)
    digest = hashlib.sha256(other.read_bytes()).hexdigest()
    installs = ("--file", str(other), "--sha256", digest)
    environ = {"ALPHAAVATAR_HOME": str(data)}
    (data / "avatars/alpha").mkdir(parents=True)
    (data / "avatars/alpha/memory.db").write_bytes(b"memories")
    assert run(extra=environ).returncode == 0
    command, at = {
        "stage": ("mktemp", ".install-XXXXXX"),
        "version": ("mv", "/tree/alphaavatar-"),
        "switch": ("mv", f" {prefix / 'current'}"),
    }[step]
    signalling(tools, command)
    to = "group" if signal == "INT" else "script"
    injected = {"INJECT_AT": at, "INJECT_SIGNAL": signal, "INJECT_WHEN": when, "INJECT_TO": to}
    stopped = run(*installs, extra=environ | injected)
    switched = step == "switch"
    assert os.readlink(prefix / "current") == f"versions/{OTHER if switched else ID}"
    assert runs(entry) == "AlphaAvatar 9.9.9\n"
    assert sorted(os.listdir(prefix / "versions")) == sorted([ID, *([OTHER] if switched else [])])
    assert (data / "avatars/alpha/memory.db").read_bytes() == b"memories"
    assert stopped.returncode == 128 + {"HUP": 1, "INT": 2, "TERM": 15}[signal], stopped.stderr
    retried = run(*installs, extra=environ)
    assert retried.returncode == 0, retried.stderr
    assert os.readlink(prefix / "current") == f"versions/{OTHER}"
    assert sorted(os.listdir(prefix / "versions")) == sorted([ID, OTHER])


def test_a_signal_as_the_command_appears_leaves_neither_it_nor_its_directories(layout) -> None:
    """SIGTERM the moment a first installation has linked its command into directories it
    made: once the link is recorded the run ends, and removes it and those directories; the
    prefix keeps the lock alone."""
    tmp_path, _, tools, run = layout
    entry = tmp_path / "made/bin/alphaavatar"
    signalling(tools, "ln")
    injected = {"INJECT_AT": str(entry), "INJECT_SIGNAL": "TERM", "INJECT_WHEN": "after"}
    stopped = run("--bin-dir", str(entry.parent), extra=injected | {"INJECT_TO": "script"})
    assert not (tmp_path / "made").exists() and not entry.is_symlink()
    assert os.listdir(tmp_path / "prefix") == [".install.lock"]
    assert stopped.returncode == 143, stopped.stderr
    retried = run("--bin-dir", str(entry.parent))
    assert retried.returncode == 0, retried.stderr
    assert runs(entry) == "AlphaAvatar 9.9.9\n"


# rm, killing the whole run partway through a stage stopped runs left: the stage's mark first
# where the mark is inside what it was given, as rm -rf may take any order.
KILLING = """#!/bin/sh
for operand; do
  case "$operand" in */.install-left*) ;; *) continue ;; esac
  if [ -f "$operand/.alphaavatar-install" ]; then
    "{real}" -f "$operand/.alphaavatar-install"
  else
    "{real}" -rf "$operand"
  fi
  kill -s KILL 0
done
exec "{real}" "$@"
"""


def test_a_run_killed_removing_a_stopped_runs_stage_leaves_it_marked_for_the_next(layout) -> None:
    tmp_path, _, tools, run = layout
    prefix, entry = tmp_path / "prefix", tmp_path / "bin/alphaavatar"
    assert run().returncode == 0
    left = prefix / "versions/.install-left"
    (left / "tree/alphaavatar-9.9.9/bin").mkdir(parents=True)
    (left / "package.tar.gz").write_bytes(b"part of a download")
    (left / ".alphaavatar-install").touch()
    (tools / "rm").write_text(KILLING.replace("{real}", shutil.which("rm")))
    (tools / "rm").chmod(0o755)
    killed = run()
    assert killed.returncode == -9
    # Still a stage of this script's, with what is left of it; current as it was.
    assert (left / ".alphaavatar-install").is_file()
    assert (
        os.readlink(prefix / "current") == f"versions/{ID}" and runs(entry) == "AlphaAvatar 9.9.9\n"
    )
    (tools / "rm").unlink()
    retried = run()
    assert retried.returncode == 0, retried.stderr
    assert os.listdir(prefix / "versions") == [ID]


# rm, refusing all in a stage but its mark, as files it may not remove would be.
REFUSING = """#!/bin/sh
for operand; do
  case "$operand" in
    */.install-*/.alphaavatar-install) ;;
    */.install-*) echo "rm: cannot remove '$operand': Permission denied" >&2; exit 1 ;;
  esac
done
exec "{real}" "$@"
"""


@pytest.mark.parametrize("removed", ["its-own", "a-stopped-runs"])
def test_a_stage_whose_removal_fails_keeps_its_mark_for_the_next_run(layout, removed: str) -> None:
    """A run's own stage as its cleanup removes it, the run having failed, or a stopped run's
    as the next removes it: the removal fails, and stops there. The stage keeps its mark and
    what is left in it; current, the command and the data are as they were; once removing
    works again, the next run removes it and installs."""
    tmp_path, _, tools, run = layout
    prefix, entry, data = tmp_path / "prefix", tmp_path / "bin/alphaavatar", tmp_path / "data"
    other = package(tmp_path / "next", package_id=OTHER)
    installs = ("--file", str(other), "--sha256", hashlib.sha256(other.read_bytes()).hexdigest())
    environ = {"ALPHAAVATAR_HOME": str(data)}
    (data / "avatars/alpha").mkdir(parents=True)
    (data / "avatars/alpha/memory.db").write_bytes(b"memories")
    assert run(extra=environ).returncode == 0
    if removed == "a-stopped-runs":
        left = prefix / "versions/.install-left"
        (left / "tree/alphaavatar-9.9.9/bin").mkdir(parents=True)
        (left / "package.tar.gz").write_bytes(b"part of a download")
        (left / ".alphaavatar-install").touch()
    (tools / "rm").write_text(REFUSING.replace("{real}", shutil.which("rm")))
    (tools / "rm").chmod(0o755)
    # Its own: the package fails its check, and the cleanup removes the stage it was copied to.
    check = ("--sha256", "0" * 64) if removed == "its-own" else installs[2:]
    failed = run(*installs[:2], *check, extra=environ)
    stages = [path for path in (prefix / "versions").iterdir() if path.name.startswith(".")]
    assert len(stages) == 1 and (stages[0] / ".alphaavatar-install").is_file()
    assert any(path.name != ".alphaavatar-install" for path in stages[0].iterdir())
    assert os.readlink(prefix / "current") == f"versions/{ID}"
    assert runs(entry) == "AlphaAvatar 9.9.9\n"
    assert (data / "avatars/alpha/memory.db").read_bytes() == b"memories"
    assert failed.returncode == 1 and "Permission denied" in failed.stderr, failed.stderr
    (tools / "rm").unlink()
    retried = run(*installs, extra=environ)
    assert retried.returncode == 0, retried.stderr
    assert os.readlink(prefix / "current") == f"versions/{OTHER}"
    assert sorted(os.listdir(prefix / "versions")) == sorted([ID, OTHER])
