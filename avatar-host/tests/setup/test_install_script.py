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

import ctypes
import functools
import hashlib
import http.server
import json
import os
import platform
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "packaging/linux/install.sh"
ID, OTHER = "9.9.9-test", "9.9.9-other"
LAUNCHER = '#!/bin/sh\n{effect}[ "$1" = --version ] && echo "AlphaAvatar {version}"\nexit 0\n'
GITHUB = "https://github.com/AlphaAvatar/AlphaAvatar/releases/"
MANIFEST = "alphaavatar-linux-x86_64.manifest.json"

pytestmark = pytest.mark.skipif(
    (platform.system(), platform.machine()) != ("Linux", "x86_64"),
    reason="install.sh installs the Linux x86_64 package",
)


def package(
    directory: Path, effect: str = "", package_id: str = ID, version: str = "9.9.9"
) -> Path:
    """A base package as install.sh reads one: one top directory, its manifest as build.sh
    writes one for a release, its command."""
    top = directory / f"alphaavatar-{package_id}"
    manifest = {
        "id": package_id,
        "version": version,
        "release": f"v{version}",
        "platform": "linux-x86_64",
        "glibc": "2.17",
        "cpu": [],
        "imports": ["json"],
    }
    (top / "share/alphaavatar").mkdir(parents=True)
    (top / "share/alphaavatar/manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (top / "python/bin").mkdir(parents=True)
    (top / "python/bin/python3").symlink_to(sys._base_executable)
    (top / "bin").mkdir()
    (top / "bin/alphaavatar").write_text(LAUNCHER.format(effect=effect, version=version))
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

    def run(
        *argv: str,
        extra: dict[str, str] | None = None,
        source: tuple[str, ...] | None = None,
        piped: str | None = None,
    ) -> subprocess.CompletedProcess:
        """install.sh with ``source`` (the good package's file by default), then ``argv``;
        ``piped``, a script's text sent to bash's stdin, as `curl … | bash` runs it."""
        if source is None:
            source = ("--file", str(good), "--sha256", digest)
        command = ["bash", "-s", "--"] if piped is not None else ["bash", str(SCRIPT)]
        command += [*source, "--prefix", str(tmp_path / "prefix")]
        command += ["--bin-dir", str(tmp_path / "bin")]
        return subprocess.run(
            [*command, *argv],
            input=piped,
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


# curl, sending each GitHub release URL to the stand-in instead; any other remote URL is
# refused, so no run reaches a network.
CURL = """#!/bin/sh
n=$#
while [ "$n" -gt 0 ]; do
  arg=$1; shift; n=$((n - 1))
  case "$arg" in
    {github}*) arg="{base}/${arg#{github}}" ;;
    {base}/*) ;;
    http://*|https://*) echo "curl: refused $arg" >&2; exit 97 ;;
  esac
  set -- "$@" "$arg"
done
exec "{real}" "$@"
"""


def sha(archive: Path) -> str:
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def inside(archive: Path) -> bytes:
    """The manifest a package holds, byte for byte."""
    with tarfile.open(archive) as tar:
        member = next(m for m in tar if m.name.endswith("/share/alphaavatar/manifest.json"))
        return tar.extractfile(member).read()


@pytest.fixture
def releases(layout):
    """GitHub's releases on loopback, laid out as GitHub serves them: a release's files under
    /download/<tag>/, and /latest/download/<file> redirecting to the latest release's; with
    the paths asked for."""
    tmp_path, _, tools, _ = layout
    root, asked = tmp_path / "github", []
    root.mkdir()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            asked.append(self.path)
            name = self.path.removeprefix("/latest/download/")
            if name != self.path and (root / "LATEST").is_file():
                self.send_response(302)
                self.send_header("Location", f"/download/{(root / 'LATEST').read_text()}/{name}")
                self.end_headers()
                return
            super().do_GET()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(root))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    curl = CURL.replace("{github}", GITHUB).replace("{base}", base)
    (tools / "curl").write_text(curl.replace("{real}", shutil.which("curl")))
    (tools / "curl").chmod(0o755)

    def publish(
        archive: Path,
        *,
        latest: bool = True,
        without: str = "",
        manifest_of: Path | None = None,
        at: str = "",
    ) -> str:
        """``archive``'s release, as release.yml publishes one: the package, its .sha256 and
        the manifest it holds (``manifest_of``'s instead), ``without`` one of them; at ``at``
        instead, a mirror's path. Returns the package's path on the stand-in."""
        version = json.loads(inside(archive))["version"]
        where = root / (at or f"download/v{version}")
        where.mkdir(parents=True, exist_ok=True)
        name = f"alphaavatar-{version}-linux-x86_64.tar.gz"
        files = {
            "package": (name, archive.read_bytes()),
            "sha256": (f"{name}.sha256", f"{sha(archive)}  {name}\n".encode()),
            "manifest": (MANIFEST, inside(manifest_of or archive)),
            "script": ("install.sh", SCRIPT.read_bytes()),
        }
        for kind, (file, data) in files.items():
            if kind != without:
                (where / file).write_bytes(data)
        if latest:
            (root / "LATEST").write_text(f"v{version}")
        return f"/{where.relative_to(root)}/{name}"

    yield publish, asked, base
    server.shutdown()
    server.server_close()


def test_with_no_source_the_latest_release_is_installed_from_that_release_alone(
    layout, releases
) -> None:
    """The latest release is named once, by its manifest; the package and its SHA-256 come
    from that release; the run says the version and build it installed."""
    tmp_path, good, _, run = layout
    publish, asked, _ = releases
    publish(package(tmp_path / "older", package_id="9.9.8-test", version="9.9.8"))
    path = publish(good)
    installed = run(source=())
    assert installed.returncode == 0, installed.stderr
    assert "The latest release is v9.9.9" in installed.stdout
    assert f"Installed AlphaAvatar 9.9.9, build {ID}:" in installed.stdout
    # The manifest through the redirect to v9.9.9's, then the package's files from there.
    manifest = [f"/latest/download/{MANIFEST}", f"/download/v9.9.9/{MANIFEST}"]
    assert asked == [*manifest, f"{path}.sha256", path]
    assert os.readlink(tmp_path / "prefix/current") == f"versions/{ID}"
    assert runs(tmp_path / "bin/alphaavatar") == "AlphaAvatar 9.9.9\n"


@pytest.mark.parametrize("given", ["version", "url", "file"])
def test_a_given_source_installs_its_package_and_asks_no_latest_release(
    layout, releases, given: str
) -> None:
    """--version, --url and --file keep their meaning beside a newer latest release."""
    tmp_path, good, _, run = layout
    publish, asked, base = releases
    older = package(tmp_path / "older", package_id="9.9.8-test", version="9.9.8")
    path = publish(older, latest=False, at="mirror" if given == "url" else "")
    publish(package(tmp_path / "newer", package_id="9.9.10-test", version="9.9.10"))
    source = {
        "version": ("--version", "9.9.8"),
        "url": ("--url", f"{base}{path}"),
        "file": ("--file", str(older), "--sha256", sha(older)),
    }[given]
    installed = run(source=source)
    assert installed.returncode == 0, installed.stderr
    assert "Installed AlphaAvatar 9.9.8, build 9.9.8-test:" in installed.stdout
    assert asked == ([] if given == "file" else [f"{path}.sha256", path])
    assert os.readlink(tmp_path / "prefix/current") == "versions/9.9.8-test"


@pytest.mark.parametrize(
    "sources",
    [
        ("--version", "--file"),
        ("--file", "--url"),
        ("--version", "--url"),
        ("--version", "--file", "--url"),
        ("--version",),  # Each given an empty value from here on.
        ("--file",),
        ("--url",),
    ],
)
def test_sources_are_one_at_most_and_the_latest_only_when_none_is_given(
    layout, releases, sources: tuple[str, ...]
) -> None:
    """Two sources are refused before anything is made or asked; so is a source given an
    empty value, which is never taken for none given, the latest release."""
    tmp_path, good, _, run = layout
    _, asked, base = releases
    value = {"--version": "9.9.9", "--file": str(good), "--url": f"{base}/x.tar.gz"}
    empty = len(sources) == 1
    refused = run(*(i for flag in sources for i in (flag, "" if empty else value[flag])), source=())
    if empty:
        assert refused.returncode == 1 and f"{sources[0]} needs a value" in refused.stderr
    else:
        assert refused.returncode == 2 and refused.stderr.startswith("usage: install.sh")
    assert not (tmp_path / "prefix").exists() and asked == []


@pytest.mark.parametrize(
    "broken", ["no release", "development build", "package", "sha256", "build"]
)
def test_a_latest_release_that_cannot_be_installed_is_refused_and_no_other_is_tried(
    layout, releases, broken: str
) -> None:
    """No latest release, one whose manifest names no release (a development build's), one
    without its package or .sha256, or whose package holds another build than its manifest
    names: the run says which and ends; no older release is tried; the installation, the
    command and the data stay as they were, and nothing of the run is left."""
    tmp_path, good, _, run = layout
    publish, asked, _ = releases
    prefix, entry, data = tmp_path / "prefix", tmp_path / "bin/alphaavatar", tmp_path / "data"
    (data / "avatars/alpha").mkdir(parents=True)
    (data / "avatars/alpha/memory.db").write_bytes(b"memories")
    environ = {"ALPHAAVATAR_HOME": str(data)}
    assert run(extra=environ).returncode == 0
    publish(package(tmp_path / "older", package_id="9.9.8-test", version="9.9.8"))
    newer = package(tmp_path / "newer", package_id="9.9.10-test", version="9.9.10")
    if broken == "development build":  # As build.sh writes one for a commit: no release.
        path = publish(newer, without="manifest")
        manifest = inside(newer).replace(b'"v9.9.10"', b"null")
        (tmp_path / "github/download/v9.9.10" / MANIFEST).write_bytes(manifest)
    elif broken == "build":
        other = package(tmp_path / "other", package_id="9.9.10-other", version="9.9.10")
        path = publish(newer, manifest_of=other)
    elif broken != "no release":
        path = publish(newer, without=broken)
    if broken == "no release":
        (tmp_path / "github/LATEST").unlink()
    asked.clear()
    failed = run(source=(), extra=environ)
    expected = {
        "no release": f"Cannot download {GITHUB}latest/download/{MANIFEST}",
        "development build": "The latest release's manifest names no release of AlphaAvatar",
        "package": f"Cannot download {GITHUB}download/v9.9.10/alphaavatar-9.9.10-linux",
        "sha256": f"No SHA-256 at {GITHUB}download/v9.9.10/alphaavatar-9.9.10-linux",
        "build": "The package of v9.9.10 holds another build than the manifest published",
    }[broken]
    assert failed.returncode == 1 and expected in failed.stderr, failed.stderr
    assert not any("v9.9.8" in path for path in asked), asked
    if broken == "sha256":  # Told before the package downloads.
        manifest = [f"/latest/download/{MANIFEST}", f"/download/v9.9.10/{MANIFEST}"]
        assert asked == [*manifest, f"{path}.sha256"]
    assert os.readlink(prefix / "current") == f"versions/{ID}"
    assert runs(entry) == "AlphaAvatar 9.9.9\n"
    assert os.listdir(prefix / "versions") == [ID]
    assert (data / "avatars/alpha/memory.db").read_bytes() == b"memories"


def test_the_latest_release_being_the_build_current_runs_keeps_its_setup_environment(
    layout, releases
) -> None:
    """Installing the build already there again keeps the setup environment over it current,
    with the capabilities setup installed; nothing is unpacked again."""
    tmp_path, good, _, run = layout
    publish, _, _ = releases
    prefix, entry = tmp_path / "prefix", tmp_path / "bin/alphaavatar"
    assert run().returncode == 0
    environment = prefix / "envs/plan-1"
    (environment / "share/alphaavatar").mkdir(parents=True)
    (environment / ".alphaavatar-setup").touch()
    (environment / "share/alphaavatar/plan.json").write_text(json.dumps({"base": ID}))
    (environment / "bin").mkdir()
    (environment / "bin/alphaavatar").write_text(
        LAUNCHER.format(effect="", version="9.9.9") + "# the environment's\n"
    )
    (environment / "bin/alphaavatar").chmod(0o755)
    (prefix / "current.new").symlink_to("envs/plan-1")
    (prefix / "current.new").rename(prefix / "current")
    publish(good)
    again = run(source=())
    assert again.returncode == 0, again.stderr
    assert f"AlphaAvatar {ID} is already installed" in again.stdout
    assert "Next: alphaavatar setup" not in again.stdout
    assert os.readlink(prefix / "current") == "envs/plan-1"
    assert "# the environment's" in (prefix / "current/bin/alphaavatar").read_text()
    assert runs(entry) == "AlphaAvatar 9.9.9\n"
    assert os.listdir(prefix / "versions") == [ID]


@pytest.mark.parametrize("cut", ["half", "all but its end"])
def test_piped_to_bash_it_runs_once_whole_and_a_script_cut_short_runs_nothing(
    layout, releases, cut: str
) -> None:
    """`curl … | bash`: bash reads the whole script before running any of it, so a download
    cut short makes and asks nothing; the whole one installs the latest release."""
    tmp_path, good, _, run = layout
    publish, asked, _ = releases
    publish(good)
    text = SCRIPT.read_text()
    short = text[: len(text) // 2] if cut == "half" else text[: text.rindex("}")]
    stopped = run(source=(), piped=short)
    # Bash's own wording for the unfinished script varies with its version and where the cut
    # falls; what it does is the same: it refuses the script, runs nothing and says why.
    assert stopped.returncode == 2 and stopped.stdout == "" and stopped.stderr, stopped.stderr
    assert not (tmp_path / "prefix").exists() and asked == []
    assert not (tmp_path / "bin").exists()
    installed = run(source=(), piped=text)
    assert installed.returncode == 0, installed.stderr
    assert os.readlink(tmp_path / "prefix/current") == f"versions/{ID}"


def documented(doc: str, holding: str) -> str:
    """The first bash block of ``doc`` that holds ``holding``, as it is written."""
    text = (ROOT / doc).read_text()
    return next(b for b in re.findall(r"```bash\n(.*?)```", text, re.S) if holding in b)


def entry(doc: str) -> str:
    """The documented install: the line of the doc's first install block that fetches it."""
    block = documented(doc, "latest/download/install.sh")
    (line,) = [line for line in block.splitlines() if "install.sh" in line]
    return line


def shell(tmp_path: Path, tools: Path, script: str, *, options: tuple[str, ...] = ()):
    """``script`` run as a person would in a fresh shell: its home the test's, and on its PATH
    only the stand-in tools and the system's, never the command's directory."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", *options, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={"HOME": str(tmp_path / "home"), "PATH": f"{tools}:/usr/bin:/bin", "LANG": "C.UTF-8"},
        cwd=work,
    )


LOGIN, INTERACTIVE = ("bash", "-l"), ("bash", "-i")


def new_terminal(home: Path, *shell: str) -> tuple[str, list[str]]:
    """Where a new terminal's shell, started as ``shell`` and reading the startup files it
    reads itself, finds alphaavatar ("" if nowhere), and its PATH; nothing but the system's
    PATH and the test's home given to it."""
    done = subprocess.run(
        [*shell, "-c", 'command -v alphaavatar; echo "$PATH"'],
        capture_output=True,
        text=True,
        timeout=60,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "TERM": "dumb"},
        stdin=subprocess.DEVNULL,
    )
    *found, path = done.stdout.splitlines() or [""]
    return (found[0] if found else ""), path.split(":")


def found_by_a_new_terminal(home: Path, profile: Path) -> str:
    """Where a shell finds alphaavatar once it has read ``profile`` ("" if nowhere): zsh's,
    with no zsh here to read it itself."""
    done = subprocess.run(
        ["sh", "-c", '. "$1" && command -v alphaavatar', "sh", str(profile)],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )
    return done.stdout.strip()


BEGIN, END = "# >>> AlphaAvatar >>>", "# <<< AlphaAvatar <<<"


@pytest.mark.parametrize(
    "files", ["none", "bash_profile", "bash_profile reading bashrc", "bash_login", "profile"]
)
def test_bash_finds_the_command_in_new_terminals_logged_in_or_not(layout, files: str) -> None:
    """Bash itself, started as a login shell and as an interactive one in a home holding the
    startup files given, finds the command, on its PATH once. Its interactive file and the one
    it reads logging in get the block, after what they hold; no file that would hide another
    is made. Installed again, nothing changes."""
    tmp_path, _, _, run = layout
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    mine = {
        "none": {},
        "bash_profile": {".bash_profile": "# mine, never reading .bashrc\n", ".profile": "# m\n"},
        "bash_profile reading bashrc": {
            ".bash_profile": "[ -f ~/.bashrc ] && . ~/.bashrc\n",
            ".bashrc": "alias ll='ls -l'\n",
        },
        "bash_login": {".bash_login": "# mine\n"},
        "profile": {".profile": "# mine\n", ".bashrc": "# mine\n"},
    }[files]
    for name, text in mine.items():
        (home / name).write_text(text)
    login = {"none": ".profile", "bash_login": ".bash_login", "profile": ".profile"}.get(
        files, ".bash_profile"
    )
    done = run(extra={"SHELL": "/bin/bash"})

    assert done.returncode == 0, done.stderr
    for name in (".bashrc", login):
        assert f"PATH: added {bin_dir} to {home / name}, for new terminals" in done.stdout
        text = (home / name).read_text()
        assert text.startswith(mine.get(name, "")) and text.count(BEGIN) == 1
    assert sorted(os.listdir(home)) == sorted({*mine, ".bashrc", login})
    for shell in (LOGIN, INTERACTIVE):
        found, path = new_terminal(home, *shell)
        assert found == str(bin_dir / "alphaavatar") and path.count(str(bin_dir)) == 1, shell
    written = {name: (home / name).read_bytes() for name in os.listdir(home)}

    again = run(extra={"SHELL": "/bin/bash"})
    assert again.returncode == 0, again.stderr
    for name in (".bashrc", login):
        assert f"PATH: {home / name} already adds {bin_dir}" in again.stdout
    assert {name: (home / name).read_bytes() for name in os.listdir(home)} == written
    assert new_terminal(home, *LOGIN)[1].count(str(bin_dir)) == 1


def test_bash_with_a_startup_file_it_cannot_write_says_so_and_configures_the_other(layout) -> None:
    if os.geteuid() == 0:
        pytest.skip("root writes a read-only file")
    tmp_path, _, _, run = layout
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    (home / ".bashrc").write_text("# mine\n")
    (home / ".bashrc").chmod(0o444)
    done = run(extra={"SHELL": "/bin/bash"})
    assert done.returncode == 0, done.stderr
    told = done.stdout.splitlines()
    assert f"PATH: not configured: cannot write {home / '.bashrc'}" in told
    assert f"PATH: added {bin_dir} to {home / '.profile'}, for new terminals" in told
    assert told[told.index("PATH: to add it yourself:") + 1] == f'  export PATH="{bin_dir}:$PATH"'
    assert f"This terminal finds alphaavatar after: source {home / '.profile'}" in told
    assert (home / ".bashrc").read_text() == "# mine\n"
    assert new_terminal(home, *LOGIN)[0] == str(bin_dir / "alphaavatar")


@pytest.mark.parametrize(("login", "file"), [("/usr/bin/zsh", ".zshrc"), ("/bin/sh", ".profile")])
def test_the_command_goes_on_path_for_new_terminals_in_the_login_shells_startup_file(
    layout, login: str, file: str
) -> None:
    """Not on PATH: a block marked as AlphaAvatar's goes into the login shell's own startup
    file, after what it holds; again, it is there already; from another directory, it is
    replaced, never added twice."""
    tmp_path, _, _, run = layout
    home = tmp_path / "home"
    profile = home / file

    def found() -> str:  # sh logging in reads ~/.profile itself; zsh is not here to.
        return (
            new_terminal(home, "sh", "-l")[0]
            if file == ".profile"
            else (found_by_a_new_terminal(home, profile))
        )

    mine = "# mine\nalias ll='ls -l'\n"
    profile.write_text(mine)
    done = run(extra={"SHELL": login})
    assert done.returncode == 0, done.stderr
    assert f"PATH: added {tmp_path / 'bin'} to {profile}, for new terminals" in done.stdout
    text = profile.read_text()
    assert text.startswith(mine) and text.count(BEGIN) == text.count(END) == 1
    assert found() == str(tmp_path / "bin/alphaavatar")
    assert f"This terminal finds alphaavatar in a new terminal, or after: source {profile}" in (
        done.stdout
    )

    again = run(extra={"SHELL": login})
    assert again.returncode == 0, again.stderr
    assert f"PATH: {profile} already adds {tmp_path / 'bin'}" in again.stdout
    assert profile.read_text() == text

    # Another installation's directory: the block now names it alone.
    other = run(
        "--prefix",
        str(tmp_path / "other"),
        "--bin-dir",
        str(tmp_path / "elsewhere"),
        extra={"SHELL": login},
    )
    assert other.returncode == 0, other.stderr
    assert f"PATH: updated {profile} with {tmp_path / 'elsewhere'}" in other.stdout
    text = profile.read_text()
    assert text.startswith(mine) and text.count(BEGIN) == 1 and str(tmp_path / "bin:") not in text
    assert found() == str(tmp_path / "elsewhere/alphaavatar")


def test_zsh_keeps_its_startup_files_where_zdotdir_says_and_a_linked_file_stays_a_link(
    layout,
) -> None:
    tmp_path, _, _, run = layout
    zdot, dotfiles = tmp_path / "zdot", tmp_path / "dotfiles"
    zdot.mkdir()
    dotfiles.mkdir()
    (dotfiles / "zshrc").write_text("# kept in dotfiles\n")
    (zdot / ".zshrc").symlink_to(dotfiles / "zshrc")
    done = run(extra={"SHELL": "/usr/bin/zsh", "ZDOTDIR": str(zdot)})
    assert done.returncode == 0, done.stderr
    assert f"PATH: added {tmp_path / 'bin'} to {zdot / '.zshrc'}" in done.stdout
    assert (zdot / ".zshrc").is_symlink() and BEGIN in (dotfiles / "zshrc").read_text()
    # The block replaced in place keeps the link too.
    other = run(
        "--prefix",
        str(tmp_path / "other"),
        "--bin-dir",
        str(tmp_path / "elsewhere"),
        extra={"SHELL": "/usr/bin/zsh", "ZDOTDIR": str(zdot)},
    )
    assert other.returncode == 0, other.stderr
    assert (zdot / ".zshrc").is_symlink()
    assert str(tmp_path / "elsewhere") in (dotfiles / "zshrc").read_text()
    assert not (tmp_path / "home/.zshrc").exists()


def test_a_directory_on_path_already_is_written_into_no_startup_file(layout) -> None:
    tmp_path, _, _, run = layout
    done = run(extra={"SHELL": "/bin/bash", "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin"})
    assert done.returncode == 0, done.stderr
    assert f"PATH: {tmp_path / 'bin'} is on PATH already" in done.stdout
    assert os.listdir(tmp_path / "home") == [] and "This terminal" not in done.stdout


def test_a_directory_named_with_spaces_quotes_and_dollars_reads_back_exactly(layout) -> None:
    tmp_path, _, _, run = layout
    odd = tmp_path / 'bin dir $HOME "q" `x` back\\slash'
    done = run("--bin-dir", str(odd), extra={"SHELL": "/bin/bash"})
    assert done.returncode == 0, done.stderr
    for shell in (LOGIN, INTERACTIVE):
        assert new_terminal(tmp_path / "home", *shell)[0] == str(odd / "alphaavatar"), shell


@pytest.mark.parametrize(
    "case", ["unknown shell", "unwritable", "unwritable, its block there", "a directory"]
)
def test_a_startup_file_left_unconfigured_is_said_so_and_the_installation_stands(
    layout, case: str
) -> None:
    """Where the block cannot be put in place, the installer says so and how to add the
    directory, claims nothing, and changes no file; the installation itself is done."""
    tmp_path, _, _, run = layout
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    profile = home / ".profile"
    # Bash itself sets SHELL from the account when it is not set: there is always one.
    login = "/usr/bin/fish" if case == "unknown shell" else "/bin/sh"
    if case.startswith("unwritable"):
        if os.geteuid() == 0:
            pytest.skip("root writes a read-only file")
        block = f"{BEGIN}\nexport PATH=/elsewhere:$PATH\n{END}\n" if "block" in case else ""
        profile.write_text(f"# mine\n{block}")
        profile.chmod(0o444)
    elif case == "a directory":
        profile.mkdir()
    before = {path: path.read_bytes() for path in home.rglob("*") if path.is_file()}
    done = run(extra={"SHELL": login})

    assert done.returncode == 0, done.stderr
    assert os.readlink(tmp_path / "prefix/current") == f"versions/{ID}"
    reason = {
        "unknown shell": "the login shell (/usr/bin/fish) is not bash, zsh or sh",
        "unwritable": f"cannot write {profile}",
        "unwritable, its block there": f"cannot write {profile}",
        "a directory": f"{profile} is not a file this installer edits",
    }[case]
    told = done.stdout.splitlines()
    assert f"PATH: not configured: {reason}" in told
    assert told[told.index("PATH: to add it yourself:") + 1] == f'  export PATH="{bin_dir}:$PATH"'
    assert f"This terminal finds alphaavatar once {bin_dir} is on PATH." in told
    assert "added" not in done.stdout and "updated" not in done.stdout
    after = {path: path.read_bytes() for path in home.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize(
    "case",
    [
        "a block, then one never ended",
        "an end never begun",
        "ended before begun",
        "one inside another",
        "never ended",
        "spaces around a marker",
    ],
)
def test_markers_out_of_order_leave_the_startup_file_as_it_was_to_the_byte(
    layout, case: str
) -> None:
    """Every marker is checked before anything is written: one out of order and the file,
    a link to it included, stays exactly as it was, its mode and time too; the installer says
    which line, and how to add the directory."""
    tmp_path, _, _, run = layout
    home, bin_dir, dotfiles = tmp_path / "home", tmp_path / "bin", tmp_path / "dotfiles"
    dotfiles.mkdir()
    profile, kept = home / ".profile", dotfiles / "profile"
    lines, reason = {
        "a block, then one never ended": (
            ["# mine", BEGIN, "old", END, "# kept", BEGIN, "# after it", "alias ll='ls -l'"],
            f"AlphaAvatar's block begun on line 6 of {profile} never ends",
        ),
        "an end never begun": (
            ["# mine", END, "# kept"],
            f"line 2 of {profile} ends AlphaAvatar's block, never begun",
        ),
        "ended before begun": (
            ["# mine", END, "# kept", BEGIN, "old"],
            f"line 2 of {profile} ends AlphaAvatar's block, never begun",
        ),
        "one inside another": (
            ["# mine", BEGIN, "old", BEGIN, "older", END, "# kept"],
            f"line 4 of {profile} begins AlphaAvatar's block inside another",
        ),
        "never ended": (
            ["# mine", BEGIN, "export PATH=/somewhere:$PATH"],
            f"AlphaAvatar's block begun on line 2 of {profile} never ends",
        ),
        "spaces around a marker": (
            ["# mine", f"  {BEGIN}\t", "# kept"],
            f"AlphaAvatar's block begun on line 2 of {profile} never ends",
        ),
    }[case]
    kept.write_bytes("\n".join(lines).encode() + b"\n")
    kept.chmod(0o640)
    profile.symlink_to(kept)
    before = (kept.read_bytes(), kept.stat(), sorted(os.listdir(dotfiles)))
    done = run(extra={"SHELL": "/bin/sh"})

    assert done.returncode == 0, done.stderr
    assert os.readlink(tmp_path / "prefix/current") == f"versions/{ID}"
    told = done.stdout.splitlines()
    assert f"PATH: not configured: {reason}" in told
    assert told[told.index("PATH: to add it yourself:") + 1] == f'  export PATH="{bin_dir}:$PATH"'
    after = (kept.read_bytes(), kept.stat(), sorted(os.listdir(dotfiles)))
    assert after[0] == before[0] and after[2] == before[2]
    assert (after[1].st_mode, after[1].st_ino, after[1].st_mtime_ns) == (
        before[1].st_mode,
        before[1].st_ino,
        before[1].st_mtime_ns,
    )
    assert profile.is_symlink() and os.listdir(home) == [".profile"]


# The package's command, as setup: what it was given as its input, whether the installer's lock
# was free, its descriptor closed and its stage removed, then a line read from that input; its
# exit as asked.
SETUP = """if [ "$1" = setup ]; then
  { [ -t 0 ] && echo stdin=terminal || echo stdin=other
    [ -e /proc/self/fd/9 ] && echo lock-descriptor=open || echo lock-descriptor=closed
    flock -n "$HOME/.local/lib/alphaavatar/.install.lock" true && echo lock=free || echo lock=held
    set -- "$HOME"/.local/lib/alphaavatar/versions/.install-*
    [ -e "$1" ] && echo stage=left || echo stage=gone
  } >> "$HOME/setup-ran"
  printf 'setup asks: '
  IFS= read -r said || said="(end of input)"
  echo "said=$said" >> "$HOME/setup-ran"
  exit "${SETUP_EXIT:-0}"
fi
"""


def terminal(
    tmp_path: Path,
    tools: Path,
    script: str,
    replies: list[tuple[str, bytes]],
    extra: dict[str, str] | None = None,
) -> tuple[int, str]:
    """``script`` in bash on a terminal of its own, a real PTY that is its controlling
    terminal, as a person runs it: each reply typed once what precedes it shows. Returns the
    exit code and what the terminal showed."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{tools}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "SHELL": "/bin/bash",
        "TERM": "dumb",
    } | (extra or {})
    controller, terminal_end = os.openpty()
    process = subprocess.Popen(
        ["setsid", "--ctty", "bash", "-c", script],
        stdin=terminal_end,
        stdout=terminal_end,
        stderr=terminal_end,
        env=env,
        cwd=work,
    )
    os.close(terminal_end)
    shown = bytearray()

    def read(until: str | None) -> None:
        deadline = time.monotonic() + 60
        while until is None or until.encode() not in shown:
            if time.monotonic() > deadline:
                raise AssertionError(f"waited for {until!r}; the terminal showed {bytes(shown)!r}")
            ready, _, _ = select.select([controller], [], [], 0.1)
            if not ready:
                continue
            try:
                chunk = os.read(controller, 65536)
            except OSError:  # Closed: everything on the terminal has ended.
                chunk = b""
            if not chunk:
                if until is None:
                    return
                raise AssertionError(f"ended before {until!r}: {bytes(shown)!r}")
            shown.extend(chunk)

    try:
        for prompt, reply in replies:
            read(prompt)
            os.write(controller, reply)
        read(None)
        return process.wait(timeout=60), shown.decode(errors="replace")
    finally:
        os.close(controller)
        if process.poll() is None:
            process.kill()
            process.wait()


OFFER = "Run alphaavatar setup now, to choose what the Avatar runs with? [Y/n] "


@pytest.mark.parametrize("answer", [b"\r", b"y\r", b"yes\r"], ids=["enter", "y", "yes"])
def test_piped_in_a_terminal_it_offers_setup_and_runs_it_on_that_terminal(
    layout, releases, answer: bytes
) -> None:
    """The README's own line, on a real terminal: installed and put on PATH, then setup is
    offered; agreed to, it runs on the terminal, its input the person's, not the download, and
    after the installer has let go of its lock."""
    tmp_path, _, tools, _ = layout
    publish, _, _ = releases
    publish(package(tmp_path / "guided", effect=SETUP))
    home = tmp_path / "home"
    status, shown = terminal(
        tmp_path, tools, entry("README.md"), [(OFFER, answer), ("setup asks: ", b"hello\r")]
    )

    assert status == 0, shown
    assert (home / "setup-ran").read_text().splitlines() == [
        "stdin=terminal",
        "lock-descriptor=closed",
        "lock=free",
        "stage=gone",
        "said=hello",
    ]
    assert "Setup: done" in shown
    assert shown.index("PATH: added") < shown.index(OFFER)
    for shell in (LOGIN, INTERACTIVE):
        assert new_terminal(home, *shell)[0] == str(home / ".local/bin/alphaavatar"), shell
    assert "doctor" not in shown.split(OFFER)[1] and "Starting the Host" not in shown


@pytest.mark.parametrize(
    "reply", [b"n\r", b"no\r", b"\x04", b"\x03"], ids=["no", "no-word", "end-of-input", "ctrl-c"]
)
def test_setup_declined_runs_nothing_and_the_installation_stands(
    layout, releases, reply: bytes
) -> None:
    tmp_path, _, tools, _ = layout
    publish, _, _ = releases
    publish(package(tmp_path / "guided", effect=SETUP))
    home = tmp_path / "home"
    # Configuration already there: an installation never touches it.
    settings = home / ".local/share/alphaavatar/settings/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"default_bundle": "mine"}\n')
    status, shown = terminal(tmp_path, tools, entry("README.md"), [(OFFER, reply)])

    assert status == 0, shown
    assert not (home / "setup-ran").exists()
    result = "cancelled, not run" if reply == b"\x03" else "not run"
    assert f"Setup: {result}. Next: alphaavatar setup" in shown
    assert os.readlink(home / ".local/lib/alphaavatar/current") == f"versions/{ID}"
    assert settings.read_text() == '{"default_bundle": "mine"}\n'


def children(parent: int | str, *name: str) -> list[int]:
    found = subprocess.run(["pgrep", "-P", str(parent), *name], capture_output=True, text=True)
    return [int(pid) for pid in found.stdout.split()]


def question_reader(installer: int, terminal: str) -> int | None:
    """The installer's child reading the answer from the terminal, if it is there yet: piped,
    the installer reads the script, so no other child of its reads the terminal."""
    for pid in children(installer):
        try:
            if os.readlink(f"/proc/{pid}/fd/0") in ("/dev/tty", terminal):
                return pid
        except OSError:
            pass
    return None


class Tracer:
    """ptrace, enough to hold a process at each fork it makes: Linux's own, through libc."""

    CONT, DETACH, GETEVENTMSG, SEIZE = 7, 17, 0x4201, 0x4206
    TRACE_FORKS = 0x2 | 0x4 | 0x8  # Its forks, vforks and clones
    FORK_EVENTS = (1, 2, 3)
    WALL = 0x40000000

    def __init__(self) -> None:
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.ptrace.restype = ctypes.c_long
        self.libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]

    def __call__(self, request: int, pid: int, addr: int = 0, data: int = 0) -> None:
        if self.libc.ptrace(request, pid, addr, data) == -1:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))

    def hold_at_fork(self, pid: int, which: Callable[[], bool], signal_number: int) -> int:
        """Follow ``pid``'s forks; at the first whose moment ``which`` names, the new process
        made and ``pid`` stopped in the kernel before it goes on, send it ``signal_number``,
        then let both go. Returns that fork's new process."""
        try:
            self(self.SEIZE, pid, 0, self.TRACE_FORKS)
        except PermissionError:
            pytest.skip("ptrace is not permitted here")
        while True:
            _, status = os.waitpid(pid, self.WALL)
            assert os.WIFSTOPPED(status), f"it ended first: {status}"
            event = status >> 16
            if event not in self.FORK_EVENTS:
                # A signal it receives, passed on; any other stop, gone on from.
                self(self.CONT, pid, 0, os.WSTOPSIG(status) if event == 0 else 0)
                continue
            made = ctypes.c_ulong()
            self(self.GETEVENTMSG, pid, 0, ctypes.addressof(made))
            os.waitpid(made.value, self.WALL)  # Its first stop; untraced from then on
            self(self.DETACH, made.value)
            if which():
                os.kill(pid, signal_number)
                self(self.DETACH, pid)
                return made.value
            self(self.CONT, pid)


def test_a_ctrl_c_before_the_installer_waits_for_its_answer_cancels_with_nothing_more_typed(
    layout, releases
) -> None:
    """Ctrl-C once the reader is there but before the installer waits for it: the installer is
    held writing its question to a terminal whose output is stopped (XOFF), the one thing it
    writes there, so it is certainly not waiting yet. Ctrl-C starts the output again and is
    all that is typed: the question is cancelled, no setup runs, the installation stands, and
    neither the reader nor its file is left."""
    tmp_path, _, tools, _ = layout
    publish, _, _ = releases
    publish(package(tmp_path / "guided", effect=SETUP))
    spare, told, pids = tmp_path / "spare", tmp_path / "told", tmp_path / "pids"
    spare.mkdir()
    # What the installer prints goes to a file: on the terminal it writes its question alone.
    # The person's shell stays, as a shell does: had it ended, the terminal's hangup would end
    # what the installer left, and hide it.
    script = (
        f'echo $$ > {pids}; exec > {told} 2>&1; {entry("README.md")}; echo "status $?"; sleep 120'
    )
    controller, terminal_end = os.openpty()
    terminal = os.ttyname(terminal_end)
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{tools}:/usr/bin:/bin",
        "SHELL": "/bin/bash",
        "TERM": "dumb",
        "TMPDIR": str(spare),
    }
    os.write(controller, b"\x13")  # Output stopped before anything is written
    process = subprocess.Popen(
        ["setsid", "--ctty", "bash", "-c", script],
        stdin=terminal_end,
        stdout=terminal_end,
        stderr=terminal_end,
        env=env,
        cwd=tmp_path,
    )
    os.close(terminal_end)

    def held(pid: int) -> bool:
        """Asleep in the kernel, as it is once its write waits for the stopped output."""
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "S"

    try:
        deadline = time.monotonic() + 60
        installer = reader = None
        while reader is None or not held(installer):
            assert time.monotonic() < deadline, told.read_text()
            if pids.exists() and installer is None:
                installer = next(iter(children(pids.read_text().strip(), "-x", "bash")), None)
            if installer is not None:  # The reader: its child reading the terminal
                reader = question_reader(installer, terminal)
            time.sleep(0.05)
        time.sleep(0.3)
        assert held(installer) and Path(f"/proc/{reader}").exists()  # Still held there
        os.write(controller, b"\x03")
        shown = bytearray()
        deadline = time.monotonic() + 30
        while "status " not in told.read_text():  # Nothing more is typed.
            assert time.monotonic() < deadline, f"it waited on: {bytes(shown)!r}"
            if select.select([controller], [], [], 0.1)[0]:
                shown.extend(os.read(controller, 65536))
        out = told.read_text()
        assert "Setup: cancelled, not run. Next: alphaavatar setup" in out and "status 0" in out
        assert not Path(f"/proc/{reader}").exists() and os.listdir(spare) == []
        assert not (tmp_path / "home/setup-ran").exists()
        assert os.readlink(tmp_path / "home/.local/lib/alphaavatar/current") == f"versions/{ID}"
    finally:
        os.close(controller)
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGHUP"])
def test_an_installer_ended_at_its_question_leaves_no_reader_on_the_terminal(
    layout, releases, signal_name: str
) -> None:
    """Ended by a signal while it asks, the installer takes its question's reader with it: no
    process is left to read a line meant for the shell the person goes on typing in, and no
    file is left behind."""
    tmp_path, _, tools, _ = layout
    publish, _, _ = releases
    publish(package(tmp_path / "guided", effect=SETUP))
    spare = tmp_path / "spare"  # Its TMPDIR
    spare.mkdir()
    pids, ended = tmp_path / "pids", tmp_path / "ended"
    # The person's shell runs the README's line and stays, as a shell does: had it ended, the
    # terminal's hangup would end what it left, and hide it.
    script = f"echo $$ > {pids}; {entry('README.md')}; echo $? > {ended}; sleep 120"
    controller, terminal_end = os.openpty()
    terminal = os.ttyname(terminal_end)
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{tools}:/usr/bin:/bin",
        "SHELL": "/bin/bash",
        "TERM": "dumb",
        "TMPDIR": str(spare),
    }
    process = subprocess.Popen(
        ["setsid", "--ctty", "bash", "-c", script],
        stdin=terminal_end,
        stdout=terminal_end,
        stderr=terminal_end,
        env=env,
        cwd=tmp_path,
    )
    os.close(terminal_end)
    shown = bytearray()

    try:
        deadline = time.monotonic() + 60
        while OFFER.encode() not in shown:
            assert time.monotonic() < deadline, bytes(shown)
            if select.select([controller], [], [], 0.1)[0]:
                shown.extend(os.read(controller, 65536))
        # The installer: the bash the download is piped to; its one child, the reader.
        (installer,) = children(pids.read_text().strip(), "-x", "bash")
        reader = question_reader(installer, terminal)
        assert reader is not None
        os.kill(installer, getattr(signal, signal_name))
        deadline = time.monotonic() + 30
        while not ended.exists() or Path(f"/proc/{reader}").exists():
            assert time.monotonic() < deadline, "the installer's reader was left"
            time.sleep(0.05)
        code = 143 if signal_name == "SIGTERM" else 129
        assert ended.read_text().strip() == str(code) and os.listdir(spare) == []
    finally:
        os.close(controller)
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGHUP"])
def test_a_signal_as_the_reader_starts_before_it_is_recorded_still_ends_it(
    layout, releases, signal_name: str
) -> None:
    """TERM or HUP once the installer has made its question's reader, before it records the
    reader's process: held by ptrace at that fork, the installer receives the signal there.
    It still ends with that signal's status and takes the reader with it, asks nothing, and
    leaves no file; the installation stands. The person's shell stays, as a shell does: had it
    ended, the terminal's hangup would end what the installer left, and hide it."""
    tmp_path, _, tools, _ = layout
    publish, _, _ = releases
    publish(package(tmp_path / "guided", effect=SETUP))
    spare, told, pids, ended = (tmp_path / name for name in ("spare", "told", "pids", "ended"))
    spare.mkdir()
    script = f"echo $$ > {pids}; {entry('README.md')} > {told} 2>&1; echo $? > {ended}; sleep 120"
    controller, terminal_end = os.openpty()
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{tools}:/usr/bin:/bin",
        "SHELL": "/bin/bash",
        "TERM": "dumb",
        "TMPDIR": str(spare),
    }
    process = subprocess.Popen(
        ["setsid", "--ctty", "bash", "-c", script],
        stdin=terminal_end,
        stdout=terminal_end,
        stderr=terminal_end,
        env=env,
        cwd=tmp_path,
    )
    os.close(terminal_end)
    try:
        deadline = time.monotonic() + 30
        installer = None
        while installer is None:  # The bash the download is piped to, as soon as it is there
            assert time.monotonic() < deadline, "the installer never started"
            if pids.exists():
                installer = next(iter(children(pids.read_text().strip(), "-x", "bash")), None)
        # The reader's fork is the first once the answer's file is made.
        reader = Tracer().hold_at_fork(
            installer, lambda: any(spare.iterdir()), getattr(signal, signal_name)
        )
        deadline = time.monotonic() + 30
        while not ended.exists() or Path(f"/proc/{reader}").exists():
            assert time.monotonic() < deadline, "the installer's reader was left"
            time.sleep(0.05)
        code = 143 if signal_name == "SIGTERM" else 129
        assert ended.read_text().strip() == str(code) and os.listdir(spare) == []
        assert "Installed AlphaAvatar" in told.read_text() and OFFER not in told.read_text()
        assert os.readlink(tmp_path / "home/.local/lib/alphaavatar/current") == f"versions/{ID}"
    finally:
        os.close(controller)
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


@pytest.mark.parametrize("ending", ["fails", "ctrl-c"])
def test_a_setup_that_fails_or_is_stopped_leaves_the_installation_and_says_which(
    layout, releases, ending: str
) -> None:
    tmp_path, _, tools, _ = layout
    publish, _, _ = releases
    publish(package(tmp_path / "guided", effect=SETUP))
    home = tmp_path / "home"
    reply = b"hello\r" if ending == "fails" else b"\x03"
    status, shown = terminal(
        tmp_path,
        tools,
        entry("README.md"),
        [(OFFER, b"y\r"), ("setup asks: ", reply)],
        extra={"SETUP_EXIT": "3"},
    )

    assert status == 0, shown  # The installer's status is the installation's.
    code = 3 if ending == "fails" else 130
    assert f"Setup: did not finish (exit {code}); AlphaAvatar stays installed." in shown
    assert os.readlink(home / ".local/lib/alphaavatar/current") == f"versions/{ID}"
    for shell in (LOGIN, INTERACTIVE):
        assert new_terminal(home, *shell)[0] == str(home / ".local/bin/alphaavatar"), shell


def test_non_interactive_in_a_terminal_installs_and_configures_but_never_asks(
    layout, releases
) -> None:
    tmp_path, _, tools, _ = layout
    publish, _, _ = releases
    publish(package(tmp_path / "guided", effect=SETUP))
    home = tmp_path / "home"
    script = entry("README.md") + " -s -- --non-interactive"
    status, shown = terminal(tmp_path, tools, script, [])

    assert status == 0, shown
    assert OFFER not in shown and "Next: alphaavatar setup" in shown
    assert not (home / "setup-ran").exists()
    for shell in (LOGIN, INTERACTIVE):
        assert new_terminal(home, *shell)[0] == str(home / ".local/bin/alphaavatar"), shell


def test_without_a_terminal_it_never_asks(layout) -> None:
    tmp_path, _, _, run = layout
    guided = package(tmp_path / "guided", effect=SETUP)
    digest = hashlib.sha256(guided.read_bytes()).hexdigest()
    done = run(source=("--file", str(guided), "--sha256", digest), extra={"SHELL": "/bin/bash"})
    assert done.returncode == 0, done.stderr
    assert OFFER not in done.stdout and "Next: alphaavatar setup" in done.stdout
    assert not (tmp_path / "home/setup-ran").exists()


def test_a_terminal_already_set_up_is_offered_no_setup(layout, releases) -> None:
    """Set up already, the bundles there stay as they are: no first setup is offered."""
    tmp_path, good, tools, run = layout
    publish, _, _ = releases
    prefix = tmp_path / "prefix"
    assert run().returncode == 0
    environment = prefix / "envs/plan-1"
    (environment / "share/alphaavatar").mkdir(parents=True)
    (environment / ".alphaavatar-setup").touch()
    (environment / "share/alphaavatar/plan.json").write_text(json.dumps({"base": ID}))
    (environment / "bin").mkdir()
    (environment / "bin/alphaavatar").write_text(LAUNCHER.format(effect=SETUP, version="9.9.9"))
    (environment / "bin/alphaavatar").chmod(0o755)
    (prefix / "current.new").symlink_to("envs/plan-1")
    (prefix / "current.new").rename(prefix / "current")
    publish(good)
    script = f"{entry('README.md')} -s -- --prefix {prefix} --bin-dir {tmp_path / 'bin'}"
    status, shown = terminal(tmp_path, tools, script, [])

    assert status == 0, shown
    assert OFFER not in shown and "Next: alphaavatar setup" not in shown
    assert not (tmp_path / "home/setup-ran").exists()


def test_an_unattended_install_that_fails_never_goes_on_to_setup(layout, releases) -> None:
    """No release to download: curl fails before writing anything. The unattended example
    downloads before it runs and stops at the first failed step, so it never goes on to setup
    and installs nothing."""
    tmp_path, _, tools, _ = layout
    _, asked, _ = releases
    # A command of that name already on PATH, to see whether anything goes on to run it.
    ran = tmp_path / "ran"
    (tools / "alphaavatar").write_text(f'#!/bin/sh\necho "$@" >> "{ran}"\n')
    (tools / "alphaavatar").chmod(0o755)
    failed = shell(tmp_path, tools, documented("docs/DEPLOY.md", "set -euo pipefail"))
    assert failed.returncode == 22, failed.stderr  # curl's own, for the missing file
    assert failed.stdout == "" and asked == ["/latest/download/install.sh"]
    assert not ran.exists() and not (tmp_path / "home/.local").exists()


def test_the_unattended_example_installs_asks_nothing_and_goes_on_by_itself(
    layout, releases
) -> None:
    """The unattended example, run whole with no terminal: installed, never asked, and its own
    next commands find the command."""
    tmp_path, _, tools, _ = layout
    publish, _, _ = releases
    publish(package(tmp_path / "guided", effect=SETUP))
    done = shell(tmp_path, tools, documented("docs/DEPLOY.md", "set -euo pipefail"))
    assert done.returncode == 0, done.stderr
    assert OFFER not in done.stdout and "Next: alphaavatar setup" in done.stdout
    # The example's own setup, the bundle given, ran with what the script gave it.
    assert (tmp_path / "home/setup-ran").read_text().splitlines()[0] == "stdin=other"
    assert os.readlink(tmp_path / "home/.local/lib/alphaavatar/current") == f"versions/{ID}"


def test_piped_a_download_that_fails_succeeds_unless_the_outer_shell_has_pipefail(
    layout, releases
) -> None:
    """Why the unattended install downloads before it runs: piped, as people run it, bash
    reads curl's empty output as an empty script and succeeds, and so does the pipeline,
    unless its shell has pipefail. Nothing is installed either way."""
    tmp_path, _, tools, _ = layout
    piped = entry("README.md")
    assert shell(tmp_path, tools, piped).returncode == 0
    assert shell(tmp_path, tools, piped, options=("-o", "pipefail")).returncode == 22
    assert not (tmp_path / "home/.local").exists()
