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
"""Installing a plan on Linux: a Python environment layered on the base package's Python.

    <prefix>/versions/<base id>/    the base package install.sh unpacked: its Python, the Host,
                                    Agents and Core, the manifest and the catalog
    <prefix>/envs/<plan id>/        a virtual environment over that Python, holding the plan's
                                    artifacts, its own alphaavatar command and plan.json
    <prefix>/current                versions/<base id> or envs/<plan id>: what the alphaavatar
                                    command runs

One installation into a prefix at a time, under the lock install.sh takes. Every artifact is
downloaded and checked against the plan before the environment exists; the environment is
checked, the command it holds included, before current switches to it, and the configuration
is enabled last. Until then a failure or signal leaves current, the command, configurations,
credentials and Avatar data as they were, and removes only what this run created.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .plan import Artifact, Plan

RELEASES = "https://github.com/AlphaAvatar/AlphaAvatar/releases/download"
LAUNCHER = """\
#!/bin/sh
# AlphaAvatar's command in a setup environment: its Python, isolated from the caller's settings.
exec "$(dirname -- "$(realpath -- "$0")")/python" -I -c \\
  'import sys; from alphaavatar.host.main import main; sys.exit(main())' "$@"
"""
PLAN_FILE = Path("share", "alphaavatar", "plan.json")  # Written last: the environment is whole.


class SetupError(RuntimeError):
    """An installation that cannot proceed; the message is safe to show."""


@dataclass(frozen=True, slots=True)
class Installation:
    prefix: Path
    base: Path  # versions/<base id>

    @classmethod
    def running(cls) -> Installation:
        """The installation this Python belongs to, by the base package's layout."""
        base = Path(sys.base_prefix).resolve().parent
        if (
            base.parent.name != "versions"
            or not (base / "share/alphaavatar/catalog.json").is_file()
        ):
            raise SetupError(
                "setup installs into an AlphaAvatar package (packaging/linux/install.sh); "
                f"{sys.base_prefix} is not one. In a checkout, `uv sync` installs everything."
            )
        return cls(base.parent.parent, base)

    @property
    def manifest(self) -> dict[str, Any]:
        return json.loads((self.base / "share/alphaavatar/manifest.json").read_text("utf-8"))

    @property
    def catalog(self) -> dict[str, Any]:
        return json.loads((self.base / "share/alphaavatar/catalog.json").read_text("utf-8"))

    @property
    def python(self) -> Path:
        return self.base / "python" / "bin" / "python3"

    def environment(self, plan: Plan) -> Path:
        return self.prefix / "envs" / plan.id[:16]

    def installed_requirements(self) -> tuple[str, ...]:
        """What the current setup environment over this base was planned for, if one is current."""
        current = self.current()
        try:
            plan = json.loads((current / PLAN_FILE).read_text("utf-8")) if current else {}
        except (OSError, ValueError):
            return ()
        if plan.get("base") != self.manifest["id"]:
            return ()
        return tuple(plan.get("requirements", ()))

    def current(self) -> Path | None:
        try:
            return (self.prefix / os.readlink(self.prefix / "current")).resolve()
        except OSError:
            return None


@dataclass(frozen=True, slots=True)
class Sources:
    """Where artifacts come from: each one's URL, and this build's own beside the package.

    A directory location is searched for every artifact first (a download cache or offline
    copy); a URL location serves only this build's own, as the release would.
    """

    location: str | None = None  # --artifacts: a directory, or a URL beside the base package
    release: str | None = None  # The base package's release tag, whose assets hold them

    def candidates(self, artifact: Artifact) -> list[str | Path]:
        found: list[str | Path] = []
        remote = self.location is not None and "://" in self.location
        if self.location is not None and not remote:
            found.append(Path(self.location) / artifact.file)
        if artifact.url is not None:
            found.append(artifact.url)
        elif remote:
            found.append(f"{self.location.rstrip('/')}/{artifact.file}")
        elif self.release is not None and self.location is None:
            found.append(f"{RELEASES}/{self.release}/{artifact.file}")
        if not found:
            raise SetupError(
                f"{artifact.file} is built with this package but not published; pass "
                "--artifacts with the directory or URL of the build that made it"
            )
        return found


def _ssl_context():
    import ssl

    paths = ssl.get_default_verify_paths()
    system = (paths.cafile and os.path.isfile(paths.cafile)) or (
        paths.capath and os.path.isdir(paths.capath) and any(os.scandir(paths.capath))
    )
    if system:
        return ssl.create_default_context()
    import certifi  # A system without a certificate store: the bundle the base package holds.

    return ssl.create_default_context(cafile=certifi.where())


def _verified(path: Path, artifact: Artifact) -> bool:
    if not path.is_file() or path.stat().st_size != artifact.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest() == artifact.sha256


def fetch(artifact: Artifact, sources: Sources, stage: Path) -> tuple[Path, bool]:
    """The artifact's verified file, and whether it is this run's own download."""
    problems = []
    for source in sources.candidates(artifact):
        if isinstance(source, Path):
            if _verified(source, artifact):
                return source, False
            problems.append(f"{source}: absent or not the planned file")
            continue
        target, partial = stage / artifact.file, stage / f"{artifact.file}.part"
        received = False
        for attempt in range(3):
            if attempt:
                time.sleep(2**attempt)
            try:
                request = urllib.request.Request(
                    source, headers={"User-Agent": "alphaavatar-setup"}
                )
                with urllib.request.urlopen(
                    request, timeout=60, context=_ssl_context()
                ) as response:
                    with partial.open("wb") as stream:
                        shutil.copyfileobj(response, stream, 1 << 20)
                received = True
                break
            except urllib.error.HTTPError as error:
                problems.append(f"{source}: HTTP {error.code}")
                if error.code < 500:
                    break
            except (OSError, urllib.error.URLError) as error:
                problems.append(f"{source}: {type(error).__name__}")
        if received and _verified(partial, artifact):
            os.replace(partial, target)
            return target, True
        partial.unlink(missing_ok=True)
        if received:
            problems.append(f"{source}: not the planned file (size or SHA-256 differ)")
    raise SetupError(f"Cannot get {artifact.file}:\n  " + "\n  ".join(dict.fromkeys(problems)))


@contextmanager
def locked(prefix: Path) -> Iterator[None]:
    prefix.mkdir(parents=True, exist_ok=True)
    with (prefix / ".install.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError(f"Another installation into {prefix} is running") from None
        yield


def _switch(prefix: Path, target: Path, stage: Path) -> None:
    link = stage / "current"
    link.unlink(missing_ok=True)
    os.symlink(os.path.relpath(target, prefix), link)
    os.replace(link, prefix / "current")


def _create(
    installation: Installation, environment: Path, wheels: list[Path], done: Callable[[Path], None]
) -> None:
    """The virtual environment over the base Python, each wheel in it, and its command."""
    from installer import install
    from installer.destinations import SchemeDictionaryDestination
    from installer.sources import WheelFile

    venv = ["-m", "venv", "--without-pip", "--system-site-packages", str(environment)]
    subprocess.run([installation.python, "-I", *venv], check=True, cwd="/")
    python = environment / "bin" / "python"
    query = "import json, sysconfig; print(json.dumps(sysconfig.get_paths()))"
    paths = json.loads(
        subprocess.run(
            [python, "-I", "-c", query], check=True, capture_output=True, text=True, cwd="/"
        ).stdout
    )
    scheme = {
        "purelib": paths["purelib"],
        "platlib": paths["platlib"],
        "headers": str(environment / "include" / "site"),
        "scripts": paths["scripts"],
        "data": paths["data"],
    }
    destination = SchemeDictionaryDestination(scheme, interpreter=str(python), script_kind="posix")
    for wheel in wheels:
        with WheelFile.open(wheel) as source:
            install(source, destination, additional_metadata={"INSTALLER": b"alphaavatar-setup\n"})
        done(wheel)
    launcher = environment / "bin" / "alphaavatar"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    launcher.chmod(0o755)


def complete(environment: Path, plan: Plan) -> bool:
    """The environment holds the plan, checked: plan.json is written last."""
    try:
        recorded = json.loads((environment / PLAN_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return False
    return recorded == plan.document()


def install(
    installation: Installation,
    plan: Plan,
    sources: Sources,
    *,
    check: Callable[[Path], None],
    enable: Callable[[], None],
    progress: Callable[[str], None] = lambda line: None,
) -> Path:
    """Install the plan into its environment, check it, switch to it, then enable.

    ``check`` runs the environment's own command before the switch; ``enable`` writes the
    configuration after it. If either fails, or a signal ends the run first, current goes back
    to what it was and the environment this run created is removed.
    """
    import signal

    prefix = installation.prefix
    environment = installation.environment(plan)
    made_envs = not (prefix / "envs").exists()
    (prefix / "envs").mkdir(parents=True, exist_ok=True)
    with locked(prefix):
        previous = installation.current()
        stage = Path(tempfile.mkdtemp(prefix=".setup-", dir=prefix / "envs"))
        created = enabled = False
        try:
            if complete(environment, plan):
                progress(f"Environment {environment} is already installed; checking it")
            else:
                if environment.exists() or environment.is_symlink():
                    # This plan's own directory, left incomplete by a run that is gone: the
                    # lock is ours, so nobody is writing it.
                    shutil.rmtree(environment)
                files = []
                for index, artifact in enumerate(plan.artifacts, 1):
                    progress(f"[{index}/{len(plan.artifacts)}] {artifact.file}")
                    files.append(fetch(artifact, sources, stage))
                owned = {path for path, mine in files if mine}
                created = True
                progress(f"Installing {len(files)} packages into {environment}")
                _create(
                    installation,
                    environment,
                    [path for path, _ in files],
                    lambda wheel: wheel.unlink() if wheel in owned else None,
                )
            progress("Checking the environment before switching to it")
            check(environment)
            if created:
                (environment / PLAN_FILE).parent.mkdir(parents=True, exist_ok=True)
                (environment / PLAN_FILE).write_text(
                    json.dumps(plan.document(), indent=1) + "\n", encoding="utf-8"
                )
            _switch(prefix, environment, stage)
            enable()
            enabled = True
        finally:
            # Whatever ends the run, the state on disk decides what to undo; signals wait.
            signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
            try:
                if not enabled and installation.current() == environment.resolve():
                    if previous is not None:
                        _switch(prefix, previous, stage)
                    else:
                        (prefix / "current").unlink()
                if created and not enabled and installation.current() != environment.resolve():
                    shutil.rmtree(environment, ignore_errors=True)
                shutil.rmtree(stage, ignore_errors=True)
                if made_envs and not enabled and not any((prefix / "envs").iterdir()):
                    (prefix / "envs").rmdir()
            finally:
                signal.pthread_sigmask(
                    signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
                )
    return environment


def check_environment(environment: Path, config: Path, env: dict[str, str]) -> None:
    """The environment's native code loads, and its command accepts the configuration."""
    for command in (
        [environment / "bin" / "python", "-I", "-m", "alphaavatar.host.setup.probe"],
        [environment / "bin" / "alphaavatar", "config", "check", str(config)],
    ):
        result = subprocess.run(command, cwd="/", env=env, capture_output=True, text=True)
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            raise SetupError(f"The new environment fails {command[-2]} {command[-1]}:\n{output}")
