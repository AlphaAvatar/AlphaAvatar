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

One installation into a prefix at a time, under the lock install.sh takes; under it the base
current runs and the requirements of its environment are read again, so a plan made before
another setup finished still keeps what that one installed. Every artifact is copied or
downloaded into this run's own stage and checked there, so what is checked is what installs.
The environment is checked, the command it holds included, before current switches to it;
the switch and enabling the configuration are one step to signals, which wait until current,
the default bundle and its credentials agree. Until then a failure or signal leaves current,
the command, configurations, credentials and Avatar data as they were. Only what carries
setup's mark and nothing references is ever removed.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
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
OWNER = ".alphaavatar-setup"  # In each directory setup makes: only those are ever removed.
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


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

    def reached(self, path: Path) -> bool:
        """``path`` is versions/<name> or envs/<name> of this prefix itself: reached through
        no symbolic link, so what it holds is this installation's to judge."""
        try:
            relative = path.relative_to(self.prefix)
        except ValueError:
            return False
        return (
            len(relative.parts) == 2
            and relative.parts[0] in ("versions", "envs")
            and path.resolve() == self.prefix.resolve() / relative
        )

    def reusable(self, plan: Plan) -> bool:
        """The plan's environment is setup's own and holds the plan, checked."""
        environment = self.environment(plan)
        return self.reached(environment) and _marked(environment) and complete(environment, plan)

    def installed_requirements(self) -> tuple[str, ...]:
        """What the current setup environment over this base was planned for, if one is current."""
        plan = self._current_plan()
        return (
            tuple(plan.get("requirements", ())) if plan.get("base") == self.manifest["id"] else ()
        )

    def current_base(self) -> str | None:
        """The base package current runs: a version, or the one its environment is over."""
        current = self.current()
        if current is None or current.parent.name == "versions":
            return current.name if current is not None else None
        return self._current_plan().get("base")

    def current(self) -> Path | None:
        """Where current points, a version or an environment of this prefix; None if absent."""
        link = self.prefix / "current"
        if not link.is_symlink():
            if link.exists():
                raise SetupError(f"{link} is not a link setup or install.sh made; left as it is")
            return None
        target = self.prefix / os.readlink(link)
        if not self.reached(target):
            raise SetupError(f"{link} points outside this installation's versions and envs")
        return target

    def _current_plan(self) -> dict[str, Any]:
        current = self.current()
        try:
            return json.loads((current / PLAN_FILE).read_text("utf-8")) if current else {}
        except (OSError, ValueError):
            return {}


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


def fetch(artifact: Artifact, sources: Sources, stage: Path) -> Path:
    """The artifact, copied or downloaded into this run's stage and verified there."""
    problems = []
    target, partial = stage / artifact.file, stage / f"{artifact.file}.part"
    for source in sources.candidates(artifact):
        if isinstance(source, Path):
            # A copy of its own: the file checked is the file installed, whatever the source does.
            try:
                shutil.copyfile(source, partial)
            except OSError as error:
                problems.append(f"{source}: {error.strerror or type(error).__name__}")
                continue
            if _verified(partial, artifact):
                os.replace(partial, target)
                return target
            partial.unlink()
            problems.append(f"{source}: not the planned file (size or SHA-256 differ)")
            continue
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
            return target
        partial.unlink(missing_ok=True)
        if received:
            problems.append(f"{source}: not the planned file (size or SHA-256 differ)")
    raise SetupError(f"Cannot get {artifact.file}:\n  " + "\n  ".join(dict.fromkeys(problems)))


@contextmanager
def locked(prefix: Path) -> Iterator[None]:
    """The lock install.sh takes too: a regular file of the prefix, opened through no link,
    waiting on no pipe put in its place, never truncated, and never removed, so every run locks
    the same file."""
    prefix.mkdir(parents=True, exist_ok=True)
    path = prefix / ".install.lock"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags, 0o644)
    except OSError as error:
        # A link, a pipe no one reads, a directory.
        if error.errno not in (errno.ELOOP, errno.ENXIO, errno.EISDIR):
            raise
        descriptor = -1
    if descriptor < 0 or not stat.S_ISREG(os.fstat(descriptor).st_mode):
        if descriptor >= 0:
            os.close(descriptor)
        raise SetupError(f"{path} is not a lock file setup or install.sh made; left as it is")
    with os.fdopen(descriptor, "a") as lock:
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


def _create(installation: Installation, environment: Path, wheels: list[Path]) -> None:
    """The virtual environment over the base Python, each wheel in it, and its command; the
    directory exists already, marked as setup's."""
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
        wheel.unlink()  # The stage's copy: space goes back as the environment grows.
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


@contextmanager
def _signals_wait() -> Iterator[None]:
    """Signals received meanwhile act once the block ends, as they would have; in whichever
    thread one arrives, Python runs its handler here."""
    received: list[int] = []
    handlers = {
        signum: signal.signal(signum, lambda signum, frame: received.append(signum))
        for signum in SIGNALS
    }
    try:
        yield
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, signal.SIG_DFL if handler is None else handler)
        for signum in dict.fromkeys(received):
            signal.raise_signal(signum)


def _marked(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and (path / OWNER).is_file()


def install(
    installation: Installation,
    plan: Plan,
    sources: Sources,
    *,
    check: Callable[[Path], None],
    enable: Callable[[], None],
    replan: Callable[[tuple[str, ...]], Plan] | None = None,
    progress: Callable[[str], None] = lambda line: None,
) -> Path:
    """Install the plan into its environment, check it, switch to it, then enable.

    ``check`` runs the environment's own command before the switch; ``enable`` writes the
    configuration after it. Under the lock, a plan missing what the current environment holds
    is made again by ``replan`` with those requirements, and one for another base refused. If
    ``check`` or ``enable`` fails, or a signal ends the run before the switch, current goes
    back to what it was and the environment this run created is removed.
    """
    prefix = installation.prefix
    with locked(prefix):
        previous = installation.current()
        if (base := installation.current_base()) not in (None, plan.base):
            raise SetupError(
                f"{prefix / 'current'} runs AlphaAvatar {base} now, not {plan.base}, which this "
                "setup belongs to; run `alphaavatar setup` again"
            )
        if missing := sorted(set(installation.installed_requirements()) - set(plan.requirements)):
            if replan is None:
                raise SetupError(f"The current environment holds {', '.join(missing)}; plan them")
            plan = replan(installation.installed_requirements())
            progress(
                f"Another setup installed {', '.join(missing)} meanwhile; kept, plan {plan.id[:16]}"
            )
        environment = installation.environment(plan)
        if (prefix / "envs").is_symlink():  # What is made through it would be elsewhere.
            raise SetupError(f"{prefix / 'envs'} is not this installation's own directory")
        made_envs = not (prefix / "envs").exists()
        (prefix / "envs").mkdir(exist_ok=True)
        for stale in (prefix / "envs").glob(".setup-*"):
            if _marked(stale):  # A stage whose run was killed: the lock is ours now.
                shutil.rmtree(stale)
        stage = Path(tempfile.mkdtemp(prefix=".setup-", dir=prefix / "envs"))
        (stage / OWNER).touch()
        created = enabled = False
        try:
            if installation.reusable(plan):
                progress(f"Environment {environment} is already installed; checking it")
            else:
                if environment.exists() or environment.is_symlink():
                    # This plan's own directory, left incomplete by a run that is gone, is
                    # rebuilt; anything else there, a link included, is not setup's to remove.
                    if not _marked(environment) or environment == previous:
                        raise SetupError(f"{environment} exists and is not setup's; left as it is")
                    shutil.rmtree(environment)
                files = []
                for index, artifact in enumerate(plan.artifacts, 1):
                    progress(f"[{index}/{len(plan.artifacts)}] {artifact.file}")
                    files.append(fetch(artifact, sources, stage))
                progress(f"Installing {len(files)} packages into {environment}")
                (stage / "env").mkdir()
                (stage / "env" / OWNER).touch()
                os.rename(stage / "env", environment)  # It appears with setup's mark.
                created = True
                _create(installation, environment, files)
            progress("Checking the environment before switching to it")
            check(environment)
            if created:
                (environment / PLAN_FILE).parent.mkdir(parents=True, exist_ok=True)
                (environment / PLAN_FILE).write_text(
                    json.dumps(plan.document(), indent=1) + "\n", encoding="utf-8"
                )
            # The switch and enabling are one step to signals: they wait until current, the
            # default bundle and its credentials agree.
            with _signals_wait():
                _switch(prefix, environment, stage)
                enable()
                enabled = True
        finally:
            # Whatever ends the run, the state on disk decides what to undo; signals wait.
            with _signals_wait():
                if not enabled and installation.current() == environment:
                    if previous is not None:
                        _switch(prefix, previous, stage)
                    else:
                        (prefix / "current").unlink()
                if created and not enabled and installation.current() != environment:
                    shutil.rmtree(environment, ignore_errors=True)
                shutil.rmtree(stage, ignore_errors=True)
                if made_envs and not enabled and not any((prefix / "envs").iterdir()):
                    (prefix / "envs").rmdir()
    return environment


def check_environment(environment: Path, config: Path | str, env: dict[str, str]) -> int:
    """The environment's native code loads, and its command accepts the configuration, a file
    or a bundle's name; the inference runners it plans, as config check counts them."""
    probe = [environment / "bin" / "python", "-I", "-m", "alphaavatar.host.setup.probe"]
    check = [environment / "bin" / "alphaavatar", "config", "check", str(config), "--json"]
    for name, command in ((" ".join(probe[-2:]), probe), (f"check {config}", check)):
        result = subprocess.run(command, cwd="/", env=env, capture_output=True, text=True)
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            with suppress(ValueError, KeyError, TypeError):
                output = json.loads(result.stdout)["error"]["diagnostic"]  # As its text shows.
            raise SetupError(f"The new environment fails {name}:\n{output}")
    return len(json.loads(result.stdout)["inference"])
