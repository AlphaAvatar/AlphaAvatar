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
"""`alphaavatar upgrade` between two builds of one version: --check names both and changes
nothing; an upgrade reports its steps, a failure what stays current, and neither writes to the
application home."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from unittest import mock

import pytest
from upgrade_samples import build, installed, listing

from alphaavatar.host.cli.app import main
from alphaavatar.host.configs import application_paths
from alphaavatar.host.tools.setup import environment

pytestmark = pytest.mark.skipif(
    (platform.system(), platform.machine()) != ("Linux", "x86_64"),
    reason="the package is the Linux x86_64 one",
)


@pytest.fixture
def builds(tmp_path: Path):
    """Build A set up for the default bundle and running this command; build B beside it."""
    prefix = tmp_path / "prefix"
    first, second = build(tmp_path / "out", "aaaa"), build(tmp_path / "out", "bbbb")
    installation = installed(prefix, first, ("alpha", "host"))
    paths = application_paths()
    paths.settings_dir.mkdir(parents=True)
    paths.settings_file.write_text("default_bundle: avatar\n")
    commands = {"UPGRADE_LOG": str(tmp_path / "commands.log"), "UPGRADE_PREFIX": str(prefix)}
    with (
        mock.patch.dict(os.environ, commands),
        mock.patch.object(environment.Installation, "running", return_value=installation),
    ):
        yield installation, first, second, paths.root


def contents(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_check_names_the_current_and_target_builds_and_changes_nothing(
    builds, capsys: pytest.CaptureFixture
) -> None:
    installation, first, second, home = builds
    before, settings = listing(installation.prefix), contents(home)
    assert main(["upgrade", "--check", "--file", str(second.package)]) == 0
    shown = capsys.readouterr().out
    assert f"OK    Upgradable to AlphaAvatar {second.id}\n" in shown
    assert f"Current      {first.id}\n" in shown and f"Target       {second.id}\n" in shown
    assert f"alphaavatar upgrade --file {second.package}\n" in shown
    assert main(["upgrade", "--check", "--file", str(first.package)]) == 0
    shown = capsys.readouterr().out
    assert f"OK    The target is current already: AlphaAvatar {first.id}\n" in shown
    assert listing(installation.prefix) == before and contents(home) == settings


def test_an_upgrade_reports_its_steps_and_a_failure_what_stays_current(
    builds, capsys: pytest.CaptureFixture
) -> None:
    installation, first, second, home = builds
    settings = contents(home)
    failed = main(["upgrade", "--file", str(second.package), "--sha256", "0" * 64])
    assert failed == 1
    refused = capsys.readouterr().err
    assert f"FAIL  Upgrade failed; AlphaAvatar {first.id} stays current\n" in refused
    assert "does not match its SHA-256: an incomplete download or another file" in refused

    assert main(["upgrade", "--file", str(second.package)]) == 0
    shown = capsys.readouterr().out
    for line in (
        f"01  Package        AlphaAvatar {second.id} · SHA-256 checked",
        "02  Plan           Bundle avatar · 3 packages · 0 MB",
        "03  Install        3 packages · 0 MB",
        "04  Validate       PASS · 2 runners",
        f"OK    Upgraded to AlphaAvatar {second.id}",
        f"      Previous     {first.id}",
        "  alphaavatar doctor avatar",
    ):
        assert f"{line}\n" in shown, shown
    assert os.readlink(installation.prefix / "current").startswith("envs/")

    # Run again, by the build now current: nothing to do.
    now = environment.Installation(
        installation.prefix, installation.prefix / "versions" / second.id
    )
    with mock.patch.object(environment.Installation, "running", return_value=now):
        assert main(["upgrade", "--file", str(second.package)]) == 0
    assert f"AlphaAvatar {second.id} is current already; nothing to do" in capsys.readouterr().out
    assert contents(home) == settings


def test_the_target_takes_a_credential_from_the_env_file_before_the_stored_one(
    builds, tmp_path: Path
) -> None:
    """Empty in the environment, a credential comes from the .env file start reads, before the
    one stored with the default bundle, for the target's plan and its check."""
    from alphaavatar.host.configs.template import create_bundle

    stored = {"UPGRADE_SECRET": "kept"}
    paths = application_paths()
    create_bundle(paths, "avatar", avatar_id="avatar", make_default=True, credentials=stored)
    dotenv = tmp_path / "chosen.env"
    dotenv.write_text("UPGRADE_SECRET=from-file\n")
    with mock.patch.dict(os.environ, {"ENV_FILE": str(dotenv), "UPGRADE_SECRET": ""}):
        assert main(["upgrade", "--file", str(builds[2].package)]) == 0
    ran = [line.split()[0] for line in (tmp_path / "commands.log").read_text().splitlines()]
    assert ran[-2:] == ["plan:avatar:from-file", "check:avatar:from-file"]


# How the target's plan and check load the bundle, in their place: as start loads it, from /,
# printing the credential an MCP server names; then the .env file changes, as it may meanwhile.
LOAD = """\
import os, sys
from pathlib import Path

from alphaavatar.agents.utils import credential
from alphaavatar.host.configs import load_application, select_configuration
from alphaavatar.host.configs.credentials import load_environment

settings = load_environment()
load_application(select_configuration(sys.argv[1], (), settings), (), settings)
print(credential("MODEL_AUTH"))
Path(os.environ["UPGRADE_DOTENV"]).write_text("MODEL_AUTH=changed\\n")
"""


def test_the_target_loads_its_bundle_with_the_env_file_this_command_read(
    builds, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run in a project with a relative ENV_FILE: a credential only the bundle names, empty in
    the environment and stored by no setup, is the file's as this command read it, for the
    target's plan and its check alike, though they run from / and the file changes meanwhile;
    never in a command line, nor in what the upgrade shows."""
    import subprocess
    import sys

    from alphaavatar.host.configs.template import create_bundle

    paths = application_paths()
    create_bundle(paths, "avatar", avatar_id="avatar", make_default=True)
    (paths.configs.profiles_dir / "avatar/plugins/tools/tools.yaml").write_text(
        "mcp:\n  plugin: default\n  enabled: true\n  servers:\n    docs:\n"
        "      url: https://mcp.invalid/\n"
        "      headers:\n        Authorization: Bearer <MODEL_AUTH>\n"
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env.dev").write_text("MODEL_AUTH=auth-from-file\n")
    monkeypatch.chdir(project)
    lines, run = [], subprocess.run

    def recorded(command, *args, **kwargs):
        lines.append(" ".join(map(str, command)))
        return run(command, *args, **kwargs)

    variables = {
        "ENV_FILE": ".env.dev",
        "MODEL_AUTH": "",
        "UPGRADE_PYTHON": sys.executable,
        "UPGRADE_LOAD": LOAD,
        "UPGRADE_DOTENV": str(project / ".env.dev"),
    }
    with mock.patch.dict(os.environ, variables), mock.patch.object(subprocess, "run", recorded):
        assert main(["upgrade", "--file", str(builds[2].package)]) == 0
    ran = [line.split()[0] for line in (tmp_path / "commands.log").read_text().splitlines()]
    assert ran[-2:] == ["plan:avatar:auth-from-file", "check:avatar:auth-from-file"]
    shown = capsys.readouterr()
    assert not [text for text in [*lines, shown.out, shown.err] if "auth-from-file" in text]
