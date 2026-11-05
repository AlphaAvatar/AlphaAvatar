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
"""`alphaavatar setup` with a preset: refused early, or enabled only after installing."""

from __future__ import annotations

import json
import os
import signal
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

from alphaavatar.host.cli.app import main
from alphaavatar.host.setup import environment
from alphaavatar.host.setup.choices import PRESETS, requirements

CREDENTIALS = {
    "OPENAI_API_KEY": "sk-fictional-0042",
    "LIVEKIT_URL": "wss://livekit.invalid",
    "LIVEKIT_API_KEY": "lk-fictional",
    "LIVEKIT_API_SECRET": "lk-fictional-secret",
}


@pytest.fixture
def package(tmp_path: Path) -> environment.Installation:
    """An installed base whose catalog holds the default preset's requirements."""
    base = tmp_path / "prefix" / "versions" / "base-1"
    (base / "share" / "alphaavatar").mkdir(parents=True)
    names = [text.split("[")[0] for text in requirements(PRESETS["default"])]
    keys = {text: [text.split("[")[0]] for text in requirements(PRESETS["default"])}
    keys |= {name: [name] for name in names}
    catalog = {
        "format": 1,
        "version": "1.0",
        "platform": "linux-x86_64",
        "base": [],
        "requirements": keys,
        "distributions": {
            name: {
                "version": "1",
                "file": f"{name}.whl",
                "sha256": "0" * 64,
                "size": 1,
                "url": None,
            }
            for name in names
        },
    }
    (base / "share/alphaavatar/catalog.json").write_text(json.dumps(catalog))
    (base / "share/alphaavatar/manifest.json").write_text(json.dumps({"id": "base-1"}))
    return environment.Installation(base.parent.parent, base)


def home_files() -> list[str]:
    home = Path.home() / ".local/share/alphaavatar"
    return sorted(str(p.relative_to(home)) for p in home.rglob("*")) if home.exists() else []


def test_setup_needs_a_package_and_a_terminal_or_a_preset(capsys: pytest.CaptureFixture) -> None:
    assert main(["setup", "--preset", "default"]) == 1  # A checkout is no package.
    assert "setup installs into an AlphaAvatar package" in capsys.readouterr().err
    with mock.patch("sys.stdin.isatty", return_value=False):
        assert main(["setup"]) == 1
    assert "pass --preset" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["setup", "--no-voice"])  # Modifiers belong to a preset.
    assert home_files() == []


def test_a_preset_is_refused_before_anything_without_its_credentials_or_with_a_taken_name(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    installed = mock.Mock(side_effect=AssertionError("nothing installs"))
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", installed),
    ):
        assert main(["setup", "--preset", "default"]) == 1
        assert "Missing credentials: OPENAI_API_KEY, LIVEKIT_URL" in capsys.readouterr().err
        assert main(["config", "init", "avatar", "--avatar-id", "avatar"]) == 0
        before = home_files()
        with mock.patch.dict(os.environ, CREDENTIALS):
            assert main(["setup", "--preset", "default"]) == 2
        assert "Bundle 'avatar' exists" in capsys.readouterr().err
        assert home_files() == before
        # The plan alone changes nothing, and is the same plan each time.
        assert main(["setup", "--preset", "remote", "--name", "remote", "--plan"]) == 0
        first = json.loads(capsys.readouterr().out)
        assert main(["setup", "--preset", "remote", "--name", "remote", "--plan"]) == 0
        assert json.loads(capsys.readouterr().out) == first
        assert first["base"] == "base-1" and first["requirements"] == list(
            requirements(PRESETS["remote"])
        )
    assert home_files() == before and not (package.prefix / "envs").exists()


def test_the_bundle_and_credentials_are_written_only_by_a_successful_install(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    assert main(["config", "init", "earlier", "--avatar-id", "earlier"]) == 0
    before = home_files()

    def failed(*args, check, enable, **kwargs):
        raise environment.SetupError("the environment fails its check")

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        assert sources == environment.Sources("/ci/run", None)
        enable()
        return installation.environment(plan)

    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.dict(os.environ, CREDENTIALS),
    ):
        with mock.patch.object(environment, "install", failed):
            assert main(["setup", "--preset", "default", "--artifacts", "/ci/run"]) == 1
        assert "nothing was enabled" in capsys.readouterr().err
        assert home_files() == before
        with mock.patch.object(environment, "install", installed):
            assert main(["setup", "--preset", "default", "--artifacts", "/ci/run"]) == 0
    home = Path.home() / ".local/share/alphaavatar"
    settings = yaml.safe_load((home / "settings/settings.yaml").read_text())
    assert settings["default_bundle"] == "avatar"  # Enabled: the new default.
    # A preset's credentials stay in the environment: nothing stores them.
    assert not (home / "settings/credentials.env").exists()
    assert "Start reads OPENAI_API_KEY, LIVEKIT_URL" in capsys.readouterr().out


def answers(*lines: str):
    """input() and getpass() answering in order, as a person at the terminal would."""
    queue = list(lines)
    return mock.patch("builtins.input", lambda prompt="": queue.pop(0)), mock.patch(
        "getpass.getpass", lambda prompt="": queue.pop(0)
    )


def test_asked_credentials_are_stored_on_a_yes_and_a_stored_one_replaced_only_on_another(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    from alphaavatar.host.configs import application_paths
    from alphaavatar.host.configs.credentials import credentials_path, store_credentials

    paths = application_paths()
    store_credentials(paths, {"OPENAI_API_KEY": "sk-earlier"})

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        enable()
        return installation.environment(plan)

    typed = ("sk-new", "wss://livekit.invalid", "lk-key", "lk-secret")
    asked, hidden = answers("1", "second", "", *typed, "y", "n", "y")
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", installed),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ),
        asked,
        hidden,
    ):
        assert main(["setup"]) == 0
    output = capsys.readouterr().out
    stored = credentials_path(paths).read_text()
    # The earlier bundle's key stays; what was new is stored, readable only by the person.
    assert 'OPENAI_API_KEY="sk-earlier"' in stored and "sk-new" not in stored
    assert 'LIVEKIT_API_SECRET="lk-secret"' in stored
    assert stat.S_IMODE(credentials_path(paths).stat().st_mode) == 0o600
    assert "OPENAI_API_KEY stays as stored" in output and "sk-new" not in output


def test_a_new_bundle_keeps_what_the_current_environment_holds(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    current = package.prefix / "envs" / "installed"
    (current / environment.PLAN_FILE).parent.mkdir(parents=True)
    os.symlink("envs/installed", package.prefix / "current")
    installed = {"base": "base-1", "requirements": list(requirements(PRESETS["default"]))}
    (current / environment.PLAN_FILE).write_text(json.dumps(installed))

    def plan() -> list[str]:
        assert main(["setup", "--preset", "remote", "--name", "remote", "--plan"]) == 0
        return json.loads(capsys.readouterr().out)["requirements"]

    with mock.patch.object(environment.Installation, "running", return_value=package):
        # Remote inference alone would drop the default bundle's models; they stay.
        assert plan() == installed["requirements"]
        # An environment over another base is not this version's to keep.
        (current / environment.PLAN_FILE).write_text(json.dumps(installed | {"base": "base-0"}))
        assert plan() == list(requirements(PRESETS["remote"]))


@pytest.mark.parametrize(
    ("replaced", "then"),
    [("credentials.env", "SIGTERM"), ("settings.yaml", "SIGTERM"), ("settings.yaml", "OSError")],
)
def test_what_ends_enabling_leaves_current_the_bundle_and_credentials_agreeing(
    package: environment.Installation, capsys: pytest.CaptureFixture, replaced: str, then: str
) -> None:
    # The base holds everything the plan needs: a real, empty environment installs.
    path = package.base / "share/alphaavatar/catalog.json"
    catalog = json.loads(path.read_text())
    path.write_text(json.dumps(catalog | {"base": sorted(catalog["distributions"])}))
    (package.base / "python/bin").mkdir(parents=True)
    (package.base / "python/bin/python3").symlink_to(sys._base_executable)
    os.symlink("versions/base-1", package.prefix / "current")
    replace = os.replace

    def replacing(source: object, target: object) -> None:
        replace(source, target)
        if Path(target).name == replaced:  # Right after the replacement.
            if then == "OSError":
                raise OSError("the settings lock cannot be released")
            os.kill(os.getpid(), signal.SIGTERM)

    typed = ("sk-new", "wss://livekit.invalid", "lk-key", "lk-secret")
    asked, hidden = answers("1", "second", "", *typed, "y", "y")
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "check_environment", lambda *args: None),
        mock.patch.object(os, "replace", replacing),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ),
        asked,
        hidden,
    ):
        assert main(["setup"]) == (0 if then == "OSError" else 128 + signal.SIGTERM)
    if then == "SIGTERM":
        assert "Stopped; bundle second was enabled first." in capsys.readouterr().err
    # All of it new: current, the default bundle and the credentials it reads.
    assert os.readlink(package.prefix / "current").startswith("envs/")
    home = Path.home() / ".local/share/alphaavatar"
    assert (
        yaml.safe_load((home / "settings/settings.yaml").read_text())["default_bundle"] == "second"
    )
    assert 'LIVEKIT_API_SECRET="lk-secret"' in (home / "settings/credentials.env").read_text()
