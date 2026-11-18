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
"""Cleaning up after an upgrade between two builds: the environments current does not run go,
then the bases no kept environment is over; what runs, what is kept and what cannot be told
the installer's stay, as the prefix is under the lock; a stopped removal leaves a marked stage
the next one removes."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from upgrade_samples import VERSION, build, installed, listing

from alphaavatar.host.configs import application_paths
from alphaavatar.host.tools.cleanup import cleanup
from alphaavatar.host.tools.setup.environment import (
    INSTALL_MARK,
    OWNER,
    PLAN_FILE,
    Installation,
    SetupError,
)
from alphaavatar.host.tools.upgrade import upgrade

pytestmark = pytest.mark.skipif(
    (platform.system(), platform.machine()) != ("Linux", "x86_64"),
    reason="the package is the Linux x86_64 one",
)


@pytest.fixture
def upgraded(tmp_path: Path):
    """A set up for the default bundle, upgraded to B: B's environment current, run by B, and
    A's version and environment beside it."""
    prefix, log = tmp_path / "prefix", tmp_path / "commands.log"
    first, second = build(tmp_path / "out", "aaaa"), build(tmp_path / "out", "bbbb")
    installation = installed(prefix, first, ("alpha", "host"))
    old = installation.current()
    paths = application_paths()
    paths.settings_dir.mkdir(parents=True)
    paths.settings_file.write_text("default_bundle: avatar\n")
    environ = dict(os.environ, UPGRADE_LOG=str(log), UPGRADE_PREFIX=str(prefix))
    new = upgrade.upgrade(
        installation, upgrade.package_file(second.package), paths=paths, environ=environ
    ).path
    return Installation(prefix, prefix / "versions" / second.id), first, second, old, new


def relative(entries, prefix: Path) -> list[str]:
    return [str(entry.path.relative_to(prefix)) for entry in entries]


def reasons(found: cleanup.Survey, prefix: Path) -> dict[str, str | None]:
    return {str(entry.path.relative_to(prefix)): entry.kept for entry in found.kept}


def runs(prefix: Path, modules: str = "alpha, beta") -> None:
    """Current's command runs the build, and its environment imports what it was set up with."""
    command = prefix / "current" / "bin" / "alphaavatar"
    ran = subprocess.run([command, "--version"], cwd="/", capture_output=True, text=True)
    assert ran.stdout == f"AlphaAvatar {VERSION}\n", ran.stderr
    python = prefix / "current" / "bin" / "python"
    imported = subprocess.run([python, "-I", "-c", f"import {modules}"], capture_output=True)
    assert imported.returncode == 0, imported.stderr


def contents(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_old_environments_go_then_the_bases_no_kept_environment_is_over(upgraded) -> None:
    now, first, second, old, new = upgraded
    prefix, paths = now.prefix, application_paths()
    # What a person keeps: a workspace's data and the model cache, beside the settings.
    for kept in (paths.avatars_dir / "avatar" / "notes.txt", paths.cache.models_dir / "w.bin"):
        kept.parent.mkdir(parents=True)
        kept.write_text("kept")
    home = contents(paths.root)
    found = cleanup.survey(now)
    current = f"envs/{new.name}"
    assert reasons(found, prefix) == {
        current: "current",
        f"versions/{second.id}": f"kept environments are over it: {current} (current)",
    }
    # The environments first, then the bases.
    assert relative(found.removable, prefix) == [f"envs/{old.name}", f"versions/{first.id}"]
    assert [entry.what for entry in found.removable] == [
        f"environment over AlphaAvatar {first.id}",
        f"AlphaAvatar {first.id}",
    ]
    assert all(entry.size > 0 for entry in found.removable)
    gone: list[cleanup.Entry] = []
    assert cleanup.cleanup(now, removed=gone.append) == found
    assert gone == list(found.removable)
    assert sorted(os.listdir(prefix / "envs")) == [new.name]
    assert sorted(os.listdir(prefix / "versions")) == [second.id]
    runs(prefix)
    assert contents(paths.root) == home
    assert cleanup.cleanup(now).removable == ()


def test_a_survey_changes_nothing(upgraded) -> None:
    now, first, second, old, new = upgraded

    def state(root: Path) -> dict[str, tuple[int, int]]:
        return {
            str(path.relative_to(root)): (path.lstat().st_mtime_ns, path.lstat().st_size)
            for path in (root, *root.rglob("*"))
        }

    before = state(now.prefix)
    assert len(cleanup.survey(now).removable) == 2
    assert state(now.prefix) == before


def spare(environment: Path) -> Path:
    """Another environment over the same base, as setup names one: its plan's ID."""
    document = json.loads((environment / PLAN_FILE).read_text()) | {"spare": True}
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    copy = environment.with_name(hashlib.sha256(text.encode()).hexdigest()[:16])
    shutil.copytree(environment, copy, symlinks=True)
    (copy / PLAN_FILE).write_text(json.dumps(document))
    return copy


@pytest.mark.parametrize("why", ["runs this command", "holds"])
def test_a_base_a_kept_environment_is_over_stays(
    upgraded, monkeypatch: pytest.MonkeyPatch, why: str
) -> None:
    now, first, second, old, new = upgraded
    prefix, keep = now.prefix, []
    if why == "runs this command":
        monkeypatch.setattr(sys, "prefix", str(old))  # Cleanup run by A's environment.
    else:
        keep = [old / "home"]  # An application home placed inside A's environment.
        keep[0].mkdir()
        why = f"holds {keep[0].resolve()}"
    found = cleanup.cleanup(now, keep=keep)
    env = f"envs/{old.name}"
    assert reasons(found, prefix)[env] == why
    assert reasons(found, prefix)[f"versions/{first.id}"] == (
        f"kept environments are over it: {env} ({why})"
    )
    assert found.removable == () and old.is_dir() and (prefix / "versions" / first.id).is_dir()


@pytest.mark.parametrize("how", ["its base rewritten", "renamed"])
def test_a_plan_that_is_not_its_environments_tells_no_base(upgraded, how: str) -> None:
    """A's plan.json names B's base, or A's environment another name: the record does not hold
    up, so A stays and no base goes on its word, while another old environment still goes."""
    now, first, second, old, new = upgraded
    prefix, other = now.prefix, spare(old)
    if how == "its base rewritten":
        plan = json.loads((old / PLAN_FILE).read_text())
        (old / PLAN_FILE).write_text(json.dumps(plan | {"base": second.id}))
    else:
        old = old.rename(old.with_name("0123456789abcdef"))
    kept, env = contents(old), f"envs/{old.name}"
    expected = {
        env: "its plan.json is not the plan it is named after",
        f"envs/{new.name}": "current",
        f"versions/{first.id}": f"the base of {env} cannot be told: no base is removed",
        f"versions/{second.id}": f"kept environments are over it: envs/{new.name} (current)",
    }
    previewed = cleanup.survey(now)
    assert reasons(previewed, prefix) == expected
    assert relative(previewed.removable, prefix) == [f"envs/{other.name}"]
    found = cleanup.cleanup(now)
    assert reasons(found, prefix) == expected and found.removable == previewed.removable
    assert not other.exists() and contents(old) == kept
    assert sorted(os.listdir(prefix / "versions")) == sorted([first.id, second.id])
    runs(prefix)


@pytest.mark.parametrize(
    ("stage", "mark"), [("envs/.setup-left", OWNER), ("versions/.install-left", INSTALL_MARK)]
)
def test_a_stage_holding_what_is_never_removed_stays(upgraded, stage: str, mark: str) -> None:
    """An application home inside a stage a stopped run left: the stage stays as an environment
    holding it would, in the preview and under the lock; what is unused still goes."""
    now, first, second, old, new = upgraded
    prefix = now.prefix
    home = prefix / stage / "app-home"
    (home / "settings").mkdir(parents=True)
    (home / "settings" / "credentials-0123456789abcdef.env").write_bytes(b'KEY="kept"\n')
    (prefix / stage / mark).touch()
    kept, why = contents(prefix / stage), f"holds {home.resolve()}"
    unused = [f"envs/{old.name}", f"versions/{first.id}"]
    previewed = cleanup.survey(now, keep=[home])
    assert reasons(previewed, prefix)[stage] == why
    assert relative(previewed.removable, prefix) == unused
    found = cleanup.cleanup(now, keep=[home])
    assert reasons(found, prefix)[stage] == why and relative(found.removable, prefix) == unused
    assert contents(prefix / stage) == kept
    assert not old.exists() and not (prefix / "versions" / first.id).exists()
    runs(prefix)


def test_what_cannot_be_told_the_installers_stays_and_keeps_every_base(upgraded) -> None:
    now, first, second, old, new = upgraded
    prefix = now.prefix
    envs, versions = prefix / "envs", prefix / "versions"
    (envs / "link").symlink_to(old)
    (envs / "notes.txt").write_text("")
    (envs / "unmarked").mkdir()
    for name, record in (("fedcba9876543210", "{"), ("0000000000000000", {"base": "../etc"})):
        (envs / name / PLAN_FILE).parent.mkdir(parents=True)
        (envs / name / OWNER).touch()
        (envs / name / PLAN_FILE).write_text(
            record if isinstance(record, str) else json.dumps(record)
        )
    (versions / "link").symlink_to(versions / second.id)
    (versions / "other" / "share/alphaavatar").mkdir(parents=True)
    (versions / "other" / "share/alphaavatar/manifest.json").write_text('{"id": "9.9.9-zzzz"}')
    foreign = listing(prefix)
    found = cleanup.cleanup(now)
    shown = reasons(found, prefix)
    for path, reason in {
        "envs/link": "a symbolic link",
        "envs/notes.txt": "not a directory",
        "envs/unmarked": "no setup mark: not an environment setup made",
        "envs/fedcba9876543210": "its plan.json cannot be read",
        "envs/0000000000000000": "its plan.json names no base in versions/",
        "versions/link": "a symbolic link",
        "versions/other": "no manifest naming it: not a base package install.sh unpacked",
    }.items():
        assert shown[path] == reason
    # Environments whose base cannot be told keep every base, A's too; A's environment goes.
    untold = "envs/0000000000000000, envs/fedcba9876543210, envs/link, envs/unmarked"
    assert (
        shown[f"versions/{first.id}"] == f"the base of {untold} cannot be told: no base is removed"
    )
    assert relative(found.removable, prefix) == [f"envs/{old.name}"]
    assert listing(prefix) == [path for path in foreign if not path.startswith(f"envs/{old.name}")]
    runs(prefix)


def test_stages_stopped_runs_left_go_and_unmarked_ones_stay(upgraded) -> None:
    now, first, second, old, new = upgraded
    prefix = now.prefix
    for stage, mark in (("envs/.setup-left", OWNER), ("versions/.install-left", INSTALL_MARK)):
        (prefix / stage / "tree").mkdir(parents=True)
        (prefix / stage / mark).touch()
    (prefix / "versions/.install-unmarked").mkdir()
    found = cleanup.cleanup(now)
    assert relative(found.removable, prefix) == [
        "envs/.setup-left",
        f"envs/{old.name}",
        "versions/.install-left",
        f"versions/{first.id}",
    ]
    assert [entry.what for entry in found.removable[::2]] == [
        "a stage a stopped setup left",
        "a stage a stopped installation left",
    ]
    assert reasons(found, prefix)["versions/.install-unmarked"].startswith("no manifest naming it")
    assert sorted(os.listdir(prefix / "versions")) == [".install-unmarked", second.id]


def test_a_stopped_removal_leaves_a_marked_stage_the_next_removes(
    upgraded, monkeypatch: pytest.MonkeyPatch
) -> None:
    now, first, second, old, new = upgraded
    prefix, rmtree = now.prefix, shutil.rmtree

    def interrupted(path, *args, **kwargs) -> None:
        if Path(path).name == "removed":
            raise KeyboardInterrupt  # Ctrl-C as A's environment goes.
        rmtree(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(shutil, "rmtree", interrupted)
        with pytest.raises(KeyboardInterrupt):
            cleanup.cleanup(now)
    # Not half an environment in place: all of it in a marked stage, and A's base untouched.
    (stage,) = (path for path in (prefix / "envs").iterdir() if path.name.startswith(".setup-"))
    assert sorted(os.listdir(stage)) == [OWNER, "removed"] and not old.exists()
    assert (prefix / "versions" / first.id).is_dir()
    runs(prefix)
    found = cleanup.cleanup(now)
    assert relative(found.removable, prefix) == [f"envs/{stage.name}", f"versions/{first.id}"]
    assert sorted(os.listdir(prefix / "envs")) == [new.name]


def test_current_and_references_are_read_again_under_the_lock(
    upgraded, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installation switches current back to A's environment between a survey and the lock:
    what is removed is what is unused once the lock is held."""
    now, first, second, old, new = upgraded
    prefix, locked = now.prefix, cleanup.locked
    assert relative(cleanup.survey(now).removable, prefix)[0] == f"envs/{old.name}"

    @contextlib.contextmanager
    def after_a_switch(where: Path):
        (prefix / "switch").symlink_to(f"envs/{old.name}")
        os.replace(prefix / "switch", prefix / "current")
        with locked(where):
            yield

    monkeypatch.setattr(cleanup, "locked", after_a_switch)
    found = cleanup.cleanup(now)
    shown = reasons(found, prefix)
    assert shown[f"envs/{old.name}"] == "current"
    assert shown[f"versions/{second.id}"] == "runs this command"
    assert relative(found.removable, prefix) == [f"envs/{new.name}"]
    assert old.is_dir() and not new.exists()
    runs(prefix, "alpha")


def test_one_cleanup_or_installation_at_a_time(upgraded) -> None:
    now, first, second, old, new = upgraded
    before = listing(now.prefix)
    with (now.prefix / ".install.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(SetupError, match="Another installation"):
            cleanup.cleanup(now)
    assert listing(now.prefix) == before


def test_a_bare_base_current_keeps_itself_and_nothing_current_keeps_all(tmp_path: Path) -> None:
    first, second = build(tmp_path / "out", "aaaa"), build(tmp_path / "out", "bbbb")
    installation = installed(tmp_path / "prefix", first, None)
    prefix = installation.prefix
    upgrade.upgrade(
        installation,
        upgrade.package_file(second.package),
        paths=application_paths(),
        environ=dict(os.environ),
    )
    now = Installation(prefix, prefix / "versions" / second.id)
    found = cleanup.survey(now)
    assert reasons(found, prefix) == {f"versions/{second.id}": "current"}
    assert relative(found.removable, prefix) == [f"versions/{first.id}"]
    # envs/ a link: what it reaches may hold environments over any base.
    (tmp_path / "elsewhere").mkdir()
    (prefix / "envs").symlink_to(tmp_path / "elsewhere")
    found = cleanup.survey(now)
    assert reasons(found, prefix)["envs"] == "a symbolic link: what it reaches is not the prefix's"
    assert reasons(found, prefix)[f"versions/{first.id}"] == (
        "the base of envs cannot be told: no base is removed"
    )
    (prefix / "current").unlink()
    with pytest.raises(SetupError, match="current is missing: nothing can be told unused"):
        cleanup.cleanup(now)
    assert sorted(os.listdir(prefix / "versions")) == sorted([first.id, second.id])
