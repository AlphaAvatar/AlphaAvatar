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
"""Removing what upgrades and setups leave in a Linux installation, within its prefix.

    <prefix>/envs/<plan id>/        setup's environments: those current does not run go first
    <prefix>/versions/<build id>/   base packages: then those no kept environment is over
    <prefix>/envs/.setup-*/         stages a stopped run left, marked as the installer's: go
    <prefix>/versions/.install-*/

Kept: the environment current points to and the base it is over, or the base current points
to; the build and environment running this; every base a kept environment is over, and every
base while a kept environment's cannot be told. So is whatever this cannot tell the installer
made, reported with why: a link, a file, a directory without the installer's mark, metadata
that cannot be read, a plan.json naming a base outside versions/ or another plan than the
environment's name, whose base is then not told by it. The application home, with
configurations, credentials, workspaces and the model cache, is outside envs/ and versions/;
``keep`` names it, and no directory holding it or inside it is removed, a stage included.

Removing takes the lock installations take and surveys again under it, current and what each
environment is over read as they are then. Each directory is moved into a marked stage first,
while signals wait, then removed with the mark last: a run stopped meanwhile leaves a stage the
next cleanup or installation removes, never part of an environment in place. The lock keeps
installations out, not a Host: ``alphaavatar start`` of the prefix stops first.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from alphaavatar.host.tools.setup.environment import (
    INSTALL_MARK,
    INSTALL_STAGE,
    OWNER,
    PLAN_FILE,
    SETUP_STAGE,
    Installation,
    SetupError,
    locked,
    marked,
    signals_deferred,
)

_BUILD = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]*")  # A build's ID, as install.sh takes one.


@dataclass(frozen=True, slots=True)
class Entry:
    """A directory of envs/ or versions/, what it is, and why it stays if it does."""

    path: Path
    what: str = ""  # Such as "AlphaAvatar 0.6.9-…" or "environment over AlphaAvatar …".
    size: int = 0  # The bytes it takes on disk, counted for what is removed.
    kept: str | None = None  # Why it stays; None: it is removed.


@dataclass(frozen=True, slots=True)
class Survey:
    current: Path  # Where current points.
    removable: tuple[Entry, ...]  # Environments and their stages first, then the bases.
    kept: tuple[Entry, ...]

    @property
    def size(self) -> int:
        return sum(entry.size for entry in self.removable)


def _size(path: Path) -> int:
    """The bytes ``path`` takes on disk, each file once, following no link."""
    seen: set[tuple[int, int]] = set()
    total = 0
    for root, directories, files in os.walk(path):
        links = [name for name in directories if os.path.islink(os.path.join(root, name))]
        for item in (root, *(os.path.join(root, name) for name in (*files, *links))):
            try:
                info = os.lstat(item)
            except OSError:
                continue
            if (info.st_dev, info.st_ino) not in seen:
                seen.add((info.st_dev, info.st_ino))
                total += info.st_blocks * 512
    return total


def _plan(environment: Path) -> tuple[str | None, str | None]:
    """The base an environment is over, as the plan.json setup writes last names it, and what
    is wrong with that record, if anything."""
    try:
        document = json.loads((environment / PLAN_FILE).read_text("utf-8"))
    except FileNotFoundError:
        return None, "no plan.json: a setup stopped before finishing it"
    except (OSError, ValueError):
        return None, "its plan.json cannot be read"
    base = document.get("base") if isinstance(document, dict) else None
    if not (isinstance(base, str) and _BUILD.fullmatch(base)):
        return None, "its plan.json names no base in versions/"
    # Setup names an environment after its plan's ID: anything else is not that plan's, and
    # the base it names is not told by it.
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(text.encode()).hexdigest()[:16] != environment.name:
        return None, "its plan.json is not the plan it is named after"
    return base, None


def _build(version: Path) -> str | None:
    """The build a directory of versions/ holds, if its manifest names it: a base package."""
    if version.is_symlink() or not version.is_dir():
        return None
    try:
        manifest = json.loads((version / "share/alphaavatar/manifest.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("id") != version.name:
        return None
    return version.name if (version / "share/alphaavatar/catalog.json").is_file() else None


def _children(directory: Path, kept: list[Entry]) -> list[Path]:
    """What envs/ or versions/ holds; nothing of a link or a file there, which is reported."""
    if directory.is_symlink():
        kept.append(Entry(directory, kept="a symbolic link: what it reaches is not the prefix's"))
        return []
    try:
        return sorted(directory.iterdir())
    except FileNotFoundError:
        return []
    except NotADirectoryError:
        kept.append(Entry(directory, kept="not a directory"))
        return []


def _foreign(path: Path, mark: str | None) -> str | None:
    """Why ``path`` is not a directory the installer made, if it is not."""
    if path.is_symlink():
        return "a symbolic link"
    if not path.is_dir():
        return "not a directory"
    if mark is not None and not marked(path, mark):
        return "no setup mark: not an environment setup made"
    return None


def survey(installation: Installation, *, keep: Iterable[Path] = ()) -> Survey:
    """What cleanup removes, and what stays and why, as the prefix is now; nothing changes.

    ``keep`` are directories never removed, nor any directory holding one or inside one.
    """
    prefix = installation.prefix
    current = installation.current()
    if current is None:
        raise SetupError(f"{prefix / 'current'} is missing: nothing can be told unused")
    # What runs this command besides current: removed, it would fail beneath itself.
    running = {installation.base.resolve(), Path(sys.prefix).resolve()}
    protected = [Path(path).resolve() for path in keep]

    def stays(path: Path) -> str | None:
        """Why ``path`` stays whatever it holds: it runs this, or holds what is never removed."""
        resolved = path.resolve()
        if resolved in running:
            return "runs this command"
        for root in protected:
            if root.is_relative_to(resolved):
                return f"holds {root}"
            if resolved.is_relative_to(root):
                return f"inside {root}"
        return None

    removable: list[Entry] = []
    kept: list[Entry] = []

    def admit(
        path: Path, what: str, first: str | None = None, then: str | None = None
    ) -> str | None:
        """Where every directory found goes, stages too: kept for the first reason there is,
        what runs this or holds what is never removed among them, or removable. The survey and
        the removal under the lock both decide here; the reason it stays is returned."""
        reason = first or stays(path) or then
        if reason is None:
            removable.append(Entry(path, what, _size(path)))
        else:
            kept.append(Entry(path, what, kept=reason))
        return reason

    over: dict[str, list[str]] = {}  # Each base kept environments are over: those, and why.
    untold: list[str] = []  # Kept environments whose base cannot be told.
    if (prefix / "envs").is_symlink():
        untold.append("envs")  # Whatever it reaches may hold environments over any base.
    for path in _children(prefix / "envs", kept):
        name = f"envs/{path.name}"
        if path.name.startswith(SETUP_STAGE) and marked(path):
            admit(path, "a stage a stopped setup left")
            continue
        foreign = _foreign(path, OWNER)
        base, problem = (None, None) if path.is_symlink() or not path.is_dir() else _plan(path)
        what = f"environment over AlphaAvatar {base}" if base else ""
        reason = admit(path, what, ("current" if path == current else None) or foreign, problem)
        if reason is None:
            continue
        if base is not None:
            over.setdefault(base, []).append(f"{name} ({reason})")
        elif path.is_dir():
            untold.append(name)
    for path in _children(prefix / "versions", kept):
        if path.name.startswith(INSTALL_STAGE) and marked(path, INSTALL_MARK):
            admit(path, "a stage a stopped installation left")
            continue
        build = _build(path)
        first = ("current" if path == current else None) or _foreign(path, None)
        if first is None and (users := over.get(path.name)):
            first = f"kept environments are over it: {', '.join(users)}"
        then = None if build else "no manifest naming it: not a base package install.sh unpacked"
        if then is None and untold:
            then = f"the base of {', '.join(untold)} cannot be told: no base is removed"
        admit(path, f"AlphaAvatar {build}" if build else "", first, then)
    return Survey(current, tuple(removable), tuple(kept))


def _remove(path: Path) -> None:
    """Moved into a marked stage of its own while signals wait, then removed, the mark last:
    stopped meanwhile, what is left is a stage the next cleanup or installation removes."""
    stage_prefix, mark = (
        (SETUP_STAGE, OWNER) if path.parent.name == "envs" else (INSTALL_STAGE, INSTALL_MARK)
    )
    if path.name.startswith(stage_prefix):
        stage = path  # A stage already, marked.
    else:
        with signals_deferred():
            stage = Path(tempfile.mkdtemp(prefix=stage_prefix, dir=path.parent))
            (stage / mark).touch()
            try:
                os.rename(path, stage / "removed")
            except OSError:
                shutil.rmtree(stage)
                raise
    for child in stage.iterdir():
        if child.name == mark:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.rmtree(stage)


def cleanup(
    installation: Installation,
    *,
    keep: Iterable[Path] = (),
    surveyed: Callable[[Survey], None] = lambda found: None,
    removed: Callable[[Entry], None] = lambda entry: None,
) -> Survey:
    """Remove what ``survey`` finds removable, surveyed again under the installation's lock:
    the environments first, then the bases. ``surveyed`` hears the survey before anything is
    removed, ``removed`` each entry once it is gone; a failure stops the run there."""
    with locked(installation.prefix):
        found = survey(installation, keep=keep)
        surveyed(found)
        for entry in found.removable:
            try:
                _remove(entry.path)
            except OSError as error:
                reason = error.strerror or type(error).__name__
                raise SetupError(f"Cannot remove {entry.path}: {reason}") from None
            removed(entry)
        return found
