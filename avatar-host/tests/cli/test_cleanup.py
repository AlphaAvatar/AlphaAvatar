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
"""`alphaavatar cleanup` after an upgrade between two builds: --dry-run lists what would go and
what stays and why, writing nothing; cleanup removes it and says what it freed; a refusal goes
to stderr. Neither touches the application home."""

from __future__ import annotations

import fcntl
import os
import platform
import subprocess
from pathlib import Path
from unittest import mock

import pytest
from upgrade_samples import VERSION, build, installed

from alphaavatar.host.cli.app import main
from alphaavatar.host.configs import application_paths
from alphaavatar.host.tools.setup import environment
from alphaavatar.host.tools.setup.environment import SetupError
from alphaavatar.host.tools.upgrade import upgrade

pytestmark = pytest.mark.skipif(
    (platform.system(), platform.machine()) != ("Linux", "x86_64"),
    reason="the package is the Linux x86_64 one",
)


@pytest.fixture
def upgraded(tmp_path: Path):
    """A set up and upgraded to B, which runs this command; A's version and environment stay."""
    prefix = tmp_path / "prefix"
    first, second = build(tmp_path / "out", "aaaa"), build(tmp_path / "out", "bbbb")
    installation = installed(prefix, first, ("alpha", "host"))
    old = installation.current()
    paths = application_paths()
    paths.settings_dir.mkdir(parents=True)
    paths.settings_file.write_text("default_bundle: avatar\n")
    commands = {"UPGRADE_LOG": str(tmp_path / "commands.log"), "UPGRADE_PREFIX": str(prefix)}
    with mock.patch.dict(os.environ, commands):
        new = upgrade.upgrade(
            installation,
            upgrade.package_file(second.package),
            paths=paths,
            environ=dict(os.environ),
        ).path
    now = environment.Installation(prefix, prefix / "versions" / second.id)
    with mock.patch.object(environment.Installation, "running", return_value=now):
        yield now, first, second, old, new, paths.root


def state(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(root)): (path.lstat().st_mtime_ns, path.lstat().st_size)
        for path in (root, *root.rglob("*"))
    }


def contents(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def line(shown: str, start: str) -> str:
    """The line of ``shown`` starting with ``start``, its padding collapsed."""
    (found,) = (row for row in shown.splitlines() if row.strip().startswith(start))
    return " ".join(found.split())


def test_a_dry_run_lists_what_would_go_and_writes_nothing(
    upgraded, capsys: pytest.CaptureFixture
) -> None:
    now, first, second, old, new, home = upgraded
    before, settings = state(now.prefix), state(home)
    assert main(["cleanup", "--dry-run"]) == 0
    shown = capsys.readouterr().out
    assert line(shown, "01").startswith("01 Survey 2 to remove · ")
    assert line(shown, "01").endswith(" MB · 2 kept")
    assert line(shown, "Current") == f"Current envs/{new.name} · AlphaAvatar {second.id}"
    assert "\nWould remove\n" in shown and "\nKept\n" in shown
    assert line(shown, f"envs/{old.name}").endswith(
        f" MB · environment over AlphaAvatar {first.id}"
    )
    assert line(shown, f"versions/{first.id}").endswith(f" MB · AlphaAvatar {first.id}")
    assert line(shown, f"envs/{new.name}") == f"envs/{new.name} current"
    assert line(shown, f"versions/{second.id}") == (
        f"versions/{second.id} kept environments are over it: envs/{new.name} (current)"
    )
    assert line(shown, "OK").startswith("OK Would free ")
    assert line(shown, "OK").endswith(" MB; nothing was removed")
    assert "  alphaavatar cleanup\n" in shown
    assert state(now.prefix) == before and state(home) == settings


def test_cleanup_removes_it_then_finds_nothing(upgraded, capsys: pytest.CaptureFixture) -> None:
    now, first, second, old, new, home = upgraded
    settings = state(home)
    assert main(["cleanup"]) == 0
    shown = capsys.readouterr().out
    assert line(shown, "02  Remove  ").startswith("02 Remove 2 removed · ")
    assert line(shown, f"Removed envs/{old.name}") == f"Removed envs/{old.name}"  # Its progress.
    assert "\nRemoved\n" in shown and line(shown, "OK").startswith("OK Freed ")
    assert sorted(os.listdir(now.prefix / "envs")) == [new.name]
    assert sorted(os.listdir(now.prefix / "versions")) == [second.id]
    assert main(["cleanup"]) == 0
    shown = capsys.readouterr().out
    assert "OK    Nothing to remove\n" in shown and "02  Remove" not in shown
    assert state(home) == settings


@pytest.mark.parametrize("environment", [{}, {"ALPHAAVATAR_HOME": ""}], ids=["unset", "empty"])
def test_the_home_the_env_file_names_stays_with_what_holds_it(
    upgraded, tmp_path: Path, capsys: pytest.CaptureFixture, environment: dict[str, str]
) -> None:
    """The .env file ENV_FILE names puts the application home inside A's environment, the
    process's own ALPHAAVATAR_HOME unset or empty, as start would then read it: A's
    environment and its base stay, in the preview and when removing, byte for byte."""
    now, first, second, old, new, home = upgraded
    inside = old / "app-home"
    (inside / "settings").mkdir(parents=True)
    (inside / "settings" / "settings.yaml").write_text("default_bundle: avatar\n")
    (tmp_path / "chosen.env").write_text(f'ALPHAAVATAR_HOME="{inside}"\n')
    kept, base = contents(old), contents(now.prefix / "versions" / first.id)
    with mock.patch.dict(os.environ, {"ENV_FILE": str(tmp_path / "chosen.env"), **environment}):
        for argv in (["cleanup", "--dry-run"], ["cleanup"]):
            assert main(argv) == 0
            shown = " ".join(capsys.readouterr().out.split())
            assert f"envs/{old.name} holds {inside.resolve()}" in shown
            assert f"versions/{first.id} kept environments are over it: envs/{old.name}" in shown
            assert "OK Nothing to remove" in shown
    assert contents(old) == kept and contents(now.prefix / "versions" / first.id) == base
    command = now.prefix / "current" / "bin" / "alphaavatar"
    ran = subprocess.run([command, "--version"], cwd="/", capture_output=True, text=True)
    assert ran.stdout == f"AlphaAvatar {VERSION}\n", ran.stderr


def test_a_refusal_says_nothing_was_removed(upgraded, capsys: pytest.CaptureFixture) -> None:
    now, first, second, old, new, home = upgraded
    before = state(now.prefix)
    with (now.prefix / ".install.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert main(["cleanup"]) == 1
    refused = capsys.readouterr().err
    assert "FAIL  Cleanup failed; nothing was removed\n" in refused
    assert f"Another installation into {now.prefix} is running" in refused
    assert state(now.prefix) == before
    with mock.patch.object(environment.Installation, "running", side_effect=SetupError("no")):
        assert main(["cleanup", "--dry-run"]) == 1
    assert "cleanup removes what upgrades leave in an AlphaAvatar package" in (
        capsys.readouterr().err
    )
