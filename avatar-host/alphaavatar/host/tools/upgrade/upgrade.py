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
"""Upgrading a Linux installation to another build, with one switch of current.

    <prefix>/versions/<target id>/   the target's base package, unpacked and checked as
                                     install.sh checks one, current left as it is
    <prefix>/envs/<plan id>/         when current is a setup environment: the target's own,
                                     for the default bundle, beside the current one

A build is told by its ID, ``<version>-<commit>``: two builds of one version are two builds.
The target is the latest release, a release's version, or a package file such as a CI build's.
A release publishes its manifest beside its package, so its build is known before anything is
downloaded; a file's is read from inside it. The package's SHA-256 is given or the .sha256
beside it, as for install.sh; each artifact's comes from the target's catalog.

Everything happens under the lock install.sh and setup take. A package file is checked where
it is first, its SHA-256 and the build it holds: the build current runs already ends the run
there, copying nothing and making no stage. Otherwise this run's own copy, checked again, is
what unpacks.

The target plans its environment: its own ``setup <bundle> --plan``, with its configuration
parser and catalog, for the default bundle, keeping what the current environment holds so
earlier bundles keep working. Its own commands check it: its command runs the target, its
native code loads, its ``config check`` accepts the bundle. The default bundle and the stored
credentials those commands read come from one read of the settings under the lock, so a setup
that ran just before is planned and checked as it left them. Only then does current switch,
once. Until then a failure or signal leaves current, the command, configurations, credentials,
workspaces and model caches as they were, and removes what this run made: a directory is
moved in and recorded as this run's while signals wait. The previous version and environment
stay; ``alphaavatar cleanup`` removes them.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alphaavatar.host.tools.setup.environment import (
    INSTALL_MARK,
    INSTALL_STAGE,
    RELEASES,
    Installation,
    SetupError,
    Sources,
    check_environment,
    check_machine,
    download,
    install_locked,
    locked,
    machine_problems,
    marked,
    megabytes,
    sha256,
    signals_deferred,
    switch_current,
)
from alphaavatar.host.tools.setup.plan import PlanError, plan_install

if TYPE_CHECKING:
    from alphaavatar.host.workspace import ApplicationPaths

LATEST = "https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download"
MANIFEST = "alphaavatar-linux-x86_64.manifest.json"  # Beside a release's package (build.sh).
PLATFORM = "linux-x86_64"
FIX = "Fix what it names, then run `alphaavatar upgrade` again"
_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]*")
_INSIDE = re.compile(r"[^/]+/share/alphaavatar/manifest\.json")
_IMPORTS = "import importlib, sys\nfor name in sys.argv[1:]:\n    importlib.import_module(name)"
_UNREADABLE = (tarfile.TarError, OSError, EOFError, zlib.error)


@dataclass(frozen=True, slots=True)
class Source:
    """Where the target's package is: a release's URL, with the manifest published beside it,
    or a file, such as a CI build's, whose manifest is inside."""

    package: str | Path
    sha256: str | None = None  # Given; otherwise the .sha256 beside the package.
    manifest: dict[str, Any] | None = None  # A release's, read before its package is.
    artifacts: str | None = None  # Where the target's own wheels are, if not the default.

    def sources(self, manifest: Mapping[str, Any]) -> Sources:
        """The target's artifacts: where given; a build's own beside its file, unless it is a
        release's; otherwise its release's."""
        if self.artifacts is None and isinstance(self.package, Path) and not manifest["release"]:
            return Sources(str(self.package.parent))
        return Sources(self.artifacts, manifest["release"])


@dataclass(frozen=True, slots=True)
class Upgraded:
    previous: str  # The build current ran.
    current: str  # The build it runs now: the same if it was the target already.
    path: Path | None = None  # Where current points, if it switched.
    runners: int | None = None  # The inference runners the new environment plans.
    bundle: str | None = None  # The default bundle, read under the lock, when current is one's.


def _checked(text: bytes, version: str | None = None) -> dict[str, Any]:
    """A package's manifest, as install.sh reads it, and holding ``version`` if one is asked."""
    try:
        manifest = json.loads(text)
    except ValueError:
        manifest = None
    fields = {"id": str, "version": str, "glibc": str, "cpu": list, "imports": list}
    if not (
        isinstance(manifest, dict)
        and all(isinstance(manifest.get(key), kind) for key, kind in fields.items())
        and _ID.fullmatch(manifest["id"])
        and manifest.get("platform") == PLATFORM
        and all(isinstance(item, str) for item in (*manifest["cpu"], *manifest["imports"]))
    ):
        raise SetupError(f"Not an AlphaAvatar {PLATFORM} package: no readable manifest")
    if version is not None and manifest["version"] != version:
        raise SetupError(f"The package holds AlphaAvatar {manifest['version']}, not {version}")
    return manifest | {"release": manifest.get("release") or None}


def release(
    version: str | None = None, *, sha256: str | None = None, artifacts: str | None = None
) -> Source:
    """The latest release's package, or ``version``'s, by the manifest published beside it."""
    if version is None:
        where, named = LATEST, "The latest release"
    else:
        where, named = f"{RELEASES}/v{version}", f"Release v{version}"
    found, problems = io.BytesIO(), []
    if not download(f"{where}/{MANIFEST}", found, problems):
        raise SetupError(
            f"{named} publishes no {PLATFORM} package:\n  " + "\n  ".join(dict.fromkeys(problems))
        )
    manifest = _checked(found.getvalue(), version)
    if manifest["release"] != f"v{manifest['version']}":
        raise SetupError(f"{named}'s manifest names no release of AlphaAvatar")
    package = (
        f"{RELEASES}/{manifest['release']}/alphaavatar-{manifest['version']}-{PLATFORM}.tar.gz"
    )
    return Source(package, sha256, manifest, artifacts)


def package_file(
    path: str | Path, *, sha256: str | None = None, artifacts: str | None = None
) -> Source:
    return Source(Path(path).expanduser().absolute(), sha256, None, artifacts)


def _expected(source: Source) -> str:
    """The package's SHA-256: given, or the first field of the .sha256 beside it."""
    if source.sha256 is not None:
        found = source.sha256
    elif isinstance(source.package, Path):
        beside = Path(f"{source.package}.sha256")
        try:
            found = (beside.read_text(encoding="utf-8").split() or [""])[0]
        except (OSError, UnicodeDecodeError):
            raise SetupError(
                f"No SHA-256: pass --sha256, or keep {beside.name} beside {source.package}"
            ) from None
    else:
        text, problems = io.BytesIO(), []
        if not download(f"{source.package}.sha256", text, problems):
            raise SetupError(f"No SHA-256 for {source.package}:\n  " + "\n  ".join(problems))
        found = (text.getvalue().decode("ascii", "replace").split() or [""])[0]
    if not re.fullmatch(r"[0-9a-f]{64}", found):
        raise SetupError(f"The SHA-256 of {source.package} is not 64 hex digits")
    return found


def _inside(package: Path) -> tuple[str, bytes]:
    """The package's top directory and its manifest's bytes."""
    try:
        with tarfile.open(package, "r:gz") as archive:
            for member in archive:
                if member.isfile() and _INSIDE.fullmatch(member.name) and member.size < 1 << 20:
                    extracted = archive.extractfile(member)
                    if extracted is not None:
                        return member.name.split("/")[0], extracted.read()
    except _UNREADABLE:
        pass
    raise SetupError("Not an AlphaAvatar package: no manifest")


def _read(package: Path, expected: str) -> dict[str, Any]:
    """A package file's manifest, read where the file is once it matches its SHA-256."""
    try:
        found = sha256(package) if package.is_file() else None
    except OSError as error:
        reason = error.strerror or type(error).__name__
        raise SetupError(f"Cannot read {package}: {reason}") from None
    if found is None:
        raise SetupError(f"No package at {package}")
    if found != expected:
        raise SetupError(
            f"{package} does not match its SHA-256: an incomplete download or another file"
        )
    return _checked(_inside(package)[1])


def inspect(source: Source) -> dict[str, Any]:
    """The target's manifest, changing nothing: a release's as published, a file's from inside
    it once the file matches its SHA-256."""
    if source.manifest is not None:
        return source.manifest
    return _read(Path(source.package), _expected(source))


def compare(current: Mapping[str, Any], target: Mapping[str, Any]) -> str:
    """``current`` for the same build, ``older`` for an earlier version, else ``upgrade``."""
    from packaging.version import InvalidVersion, Version

    if target["id"] == current["id"]:
        return "current"
    try:
        older = Version(target["version"]) < Version(current["version"])
    except InvalidVersion:
        raise SetupError(f"AlphaAvatar {target['version']} has no comparable version") from None
    return "older" if older else "upgrade"


def current_manifest(installation: Installation) -> dict[str, Any]:
    """The manifest of the build current runs, which must be the one running this command."""
    if (base := installation.current_base()) != installation.base.name:
        raise SetupError(
            f"{installation.prefix / 'current'} runs {f'AlphaAvatar {base}' if base else 'nothing'}"
            f", not AlphaAvatar {installation.base.name}, which runs this upgrade; run "
            "`alphaavatar upgrade` again"
        )
    return installation.manifest


def _package(source: Source, expected: str, stage: Path, progress: Callable[[str], None]) -> Path:
    """The package, this run's own copy in the stage, matching its SHA-256: what is checked is
    what unpacks, whatever happens to the source meanwhile."""
    package = stage / "package.tar.gz"
    if isinstance(source.package, Path):
        try:
            shutil.copyfile(source.package, package)
        except OSError as error:
            reason = error.strerror or type(error).__name__
            raise SetupError(f"Cannot copy {source.package}: {reason}") from None
    else:
        progress(f"Downloading {source.package}")
        problems: list[str] = []
        with package.open("wb") as stream:
            if not download(source.package, stream, problems):
                raise SetupError("Cannot download the package:\n  " + "\n  ".join(problems))
    if sha256(package) != expected:
        raise SetupError(
            f"{source.package} does not match its SHA-256: an incomplete download or another file"
        )
    return package


def _unpack(package: Path, stage: Path, top: str) -> Path:
    """The package unpacked in the stage, nothing outside it: one top directory."""
    tree = stage / "tree"
    tree.mkdir()
    try:
        with tarfile.open(package, "r:gz") as archive:
            archive.extractall(tree, filter="data")
    except _UNREADABLE as error:
        raise SetupError(f"The package does not unpack: {error}") from None
    found = list(tree.iterdir())
    if len(found) != 1 or found[0].name != top or found[0].is_symlink() or not found[0].is_dir():
        raise SetupError("Not an AlphaAvatar package: expected one top-level directory")
    return found[0]


def _reports(command: Path, version: str, environ: Mapping[str, str]) -> None:
    """``command`` runs from /, as AlphaAvatar ``version``."""
    run = subprocess.run(
        [command, "--version"], cwd="/", env=environ, capture_output=True, text=True
    )
    if run.returncode != 0 or run.stdout.strip() != f"AlphaAvatar {version}":
        said = (run.stdout + run.stderr).strip()[-2000:] or f"exit status {run.returncode}"
        raise SetupError(f"{command} does not run AlphaAvatar {version}:\n{said}")


def _check_base(base: Path, manifest: Mapping[str, Any], environ: Mapping[str, str]) -> None:
    """As install.sh checks a base, from /: its command, its help, and each native library it
    loads before anything switches to it."""
    _reports(base / "bin" / "alphaavatar", manifest["version"], environ)
    python = [base / "python" / "bin" / "python3", "-I", "-c", _IMPORTS, *manifest["imports"]]
    for name, command in (
        ("--help", [base / "bin" / "alphaavatar", "--help"]),
        ("imports", python),
    ):
        run = subprocess.run(command, cwd="/", env=environ, capture_output=True, text=True)
        if run.returncode != 0:
            said = (run.stdout + run.stderr).strip()[-2000:]
            raise SetupError(
                f"AlphaAvatar {manifest['id']} does not run on this machine ({name}):\n{said}"
            )


def _requirements(
    base: Path, target: str, bundle: str, environ: Mapping[str, str]
) -> tuple[str, ...]:
    """What the bundle needs, as the target's own setup plans it from the bundle's settings."""
    run = subprocess.run(
        [base / "bin" / "alphaavatar", "setup", bundle, "--plan"],
        cwd="/",
        env={**environ, "NO_COLOR": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    try:
        document = json.loads(run.stdout)
    except ValueError:
        document = None
    needed = document.get("requirements") if isinstance(document, dict) else None
    if run.returncode == 0 and isinstance(needed, list) and all(isinstance(r, str) for r in needed):
        return tuple(needed)
    try:
        said = document["error"]["diagnostic"]  # As its report shows it.
    except (KeyError, TypeError):
        said = (run.stdout + run.stderr).strip()[-2000:]
    raise SetupError(f"AlphaAvatar {target} does not plan bundle {bundle}:\n{said}\n{FIX}")


def upgrade(
    installation: Installation,
    source: Source,
    *,
    paths: ApplicationPaths,
    environ: Mapping[str, str],
    file: Mapping[str, str] | None = None,
    step: Callable[[int, str, str | None], None] = lambda number, name, summary: None,
    progress: Callable[[str], None] = lambda line: None,
) -> Upgraded:
    """Upgrade current to the target build, checked whole before current switches to it.

    Under the lock, one read of the settings of ``paths`` gives the default bundle, whose
    environment the target plans when current is a setup environment, and the credentials
    stored for it; the target's commands run with ``environ`` filled as start fills it, the
    default credentials and the stored ones: a value ``environ`` holds wins, an empty or blank
    one gives way to the .env file's (``file``, as ``load_env_file`` loaded it), then to the
    stored one. Those its bundle names the target fills as it loads it. ``step`` hears each step
    begin (summary None) and end; ``progress`` what goes on within one.
    """
    from alphaavatar.host.configs.credentials import (
        DEFAULT_CREDENTIALS,
        fill_credentials,
        read_stored,
    )

    prefix = installation.prefix
    with locked(prefix):
        previous, current = installation.current(), current_manifest(installation)
        # Read once the lock is ours: a setup that ran meanwhile has enabled what it enables,
        # and the plan and the check take the same bundle and credentials.
        settings = read_stored(paths)
        environ, stored = dict(environ), settings.credentials
        fill_credentials(environ, (*DEFAULT_CREDENTIALS, *stored), file or {}, stored)
        bundle = None
        if previous is not None and previous.parent.name == "envs":
            bundle = settings.checked().get("default_bundle")
        if source.manifest is not None and compare(current, source.manifest) == "current":
            return Upgraded(current["id"], current["id"], bundle=bundle)
        step(1, "Package", None)
        expected = _expected(source)
        # A file is read where it is: the build current runs already needs no copy, nor a stage.
        found = source.manifest or _read(Path(source.package), expected)
        verdict = compare(current, found)
        if verdict == "current":
            step(1, "Package", f"AlphaAvatar {found['id']} · current already")
            return Upgraded(current["id"], current["id"], bundle=bundle)
        if verdict == "older":
            raise SetupError(
                f"AlphaAvatar {found['id']} is older than the current {current['version']}"
                "; upgrade does not go back"
            )
        if problems := machine_problems(found["glibc"], found["cpu"]):
            raise SetupError(f"AlphaAvatar {found['id']} needs " + "; ".join(problems))
        versions = prefix / "versions"
        for stale in versions.glob(f"{INSTALL_STAGE}*"):
            # A stage whose run was killed, marked as install.sh's or this: the lock is ours now.
            if marked(stale, INSTALL_MARK):
                shutil.rmtree(stale)
        stage: Path | None = None
        fresh: Path | None = None
        try:
            with signals_deferred():  # It appears marked, and this run's to remove.
                stage = Path(tempfile.mkdtemp(prefix=INSTALL_STAGE, dir=versions))
                (stage / INSTALL_MARK).touch()
            package = _package(source, expected, stage, progress)
            top, text = _inside(package)
            manifest = _checked(text, found["version"])
            if manifest["id"] != found["id"]:
                named = "its release's manifest names" if source.manifest else "it held when read"
                raise SetupError(
                    f"{source.package} holds AlphaAvatar {manifest['id']}, not the "
                    f"{found['id']} {named}"
                )
            base = versions / manifest["id"]
            if base.exists() or base.is_symlink():
                # Unpacked by install.sh or a run that is gone: the same manifest, or not ours.
                try:
                    same = (base / "share/alphaavatar/manifest.json").read_bytes() == text
                except OSError:
                    same = False
                if not (same and installation.reached(base)):
                    raise SetupError(f"{base} exists and holds something else; left as it is")
                progress(f"AlphaAvatar {manifest['id']} is unpacked already; checking it")
            else:
                progress("Unpacking the package")
                tree = _unpack(package, stage, top)
                with signals_deferred():  # In place and this run's at once, whatever arrives.
                    os.rename(tree, base)
                    fresh = base  # Removed at the end unless current runs it.
            package.unlink()
            progress(f"Checking AlphaAvatar {manifest['id']}")
            _check_base(base, manifest, environ)
            step(1, "Package", f"AlphaAvatar {manifest['id']} · SHA-256 checked")
            target = Installation(prefix, base)
            entry = prefix / "current" / "bin" / "alphaavatar"
            if previous is not None and previous.parent.name == "versions":
                step(2, "Plan", "No setup environment: the base alone")
                with signals_deferred():
                    switch_current(prefix, base, stage)
                    try:
                        _reports(entry, manifest["version"], environ)
                    except BaseException:
                        switch_current(prefix, previous, stage)
                        raise
                return Upgraded(current["id"], manifest["id"], base, bundle=bundle)
            if bundle is None:
                raise SetupError(
                    "No default bundle: the environment current runs is for none; "
                    "`alphaavatar setup <bundle>` enables one"
                )
            step(2, "Plan", None)
            needed = _requirements(base, manifest["id"], bundle, environ)
            kept = installation.installed_requirements()
            try:
                plan = plan_install(target.catalog, {*needed, *kept}, base=manifest["id"])
            except PlanError as error:
                raise SetupError(
                    f"AlphaAvatar {manifest['id']} cannot keep what the current environment "
                    f"holds: {error}"
                ) from None
            if extra := sorted(set(kept) - set(needed)):
                progress(f"Kept from the current environment: {', '.join(extra)}")
            check_machine(target, plan)
            size = "installed already" if target.reusable(plan) else megabytes(plan.download_bytes)
            planned = f"{len(plan.artifacts)} packages · {size}"
            step(2, "Plan", f"Bundle {bundle} · {planned}")
            runners: list[int] = []

            def check(environment: Path) -> None:
                step(3, "Install", planned)
                step(4, "Validate", None)
                try:
                    _reports(environment / "bin" / "alphaavatar", manifest["version"], environ)
                    runners.append(check_environment(environment, bundle, dict(environ)))
                except SetupError as error:
                    raise SetupError(f"{error}\n{FIX}") from None
                step(4, "Validate", f"PASS · {runners[0]} runners")

            step(3, "Install", None)
            environment = install_locked(
                target,
                plan,
                source.sources(manifest),
                check=check,
                # Through current itself: what it points to runs the target.
                enable=lambda: _reports(entry, manifest["version"], environ),
                replacing=current["id"],
                progress=progress,
            )
            return Upgraded(current["id"], manifest["id"], environment, runners[0], bundle)
        finally:
            with signals_deferred():
                if fresh is not None and installation.current_base() != fresh.name:
                    shutil.rmtree(fresh, ignore_errors=True)
                if stage is not None:
                    shutil.rmtree(stage, ignore_errors=True)
