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
"""doctor: read-only and offline, config check's selection rules, exit codes, one report."""

from __future__ import annotations

import json
import shutil
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from config_samples import CONFIG, SECRETS, files, write

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.doctor import CHECKS

IDS = [spec.id for spec in CHECKS]
UNVERIFIED = ("models.runners", "services.external", "devices.media")
PATHS = ("paths.home", "paths.cache", "paths.workspace")


@pytest.fixture
def disk() -> SimpleNamespace:
    """Free space is an input of the machine; tests choose it."""
    space = SimpleNamespace(free=64 << 30)
    with mock.patch.object(shutil, "disk_usage", lambda path: space):
        yield space


def doctor(capsys: pytest.CaptureFixture, *argv: str) -> tuple[int, dict[str, dict], str]:
    """Text and JSON reports of one run; the text shows each check exactly as the JSON."""
    code = main(["doctor", *argv])
    text = capsys.readouterr().out
    assert main(["doctor", *argv, "--json"]) == code
    raw = capsys.readouterr().out
    report = json.loads(raw)
    assert [check["id"] for check in report["checks"]] == IDS
    lines = text.splitlines()
    for check in report["checks"]:
        heading = f"{check['status']}  {check['id'].ljust(21)}  {check['summary']}"
        assert f"    {heading}" in lines
    return code, {check["id"]: check for check in report["checks"]}, text + raw


def test_without_a_configuration_doctor_says_how_to_create_one_and_checks_the_rest(
    tmp_path: Path, home: Path, sandbox: list[str], disk: object, capsys: pytest.CaptureFixture
) -> None:
    before = files(tmp_path)
    code, checks, _ = doctor(capsys)
    # A missing configuration warns; the installation is still checked; nothing fails.
    assert code == 0
    assert {check: report["status"] for check, report in checks.items()} == {
        "system.platform": "PASS",
        "python.version": "PASS",
        "packages.alphaavatar": "PASS",
        "config.load": "WARN",
        "config.runners": "SKIP",
        "packages.capabilities": "SKIP",
        "paths.home": "PASS",
        "paths.cache": "PASS",
        "paths.workspace": "SKIP",
        "models.runners": "SKIP",
        "services.external": "SKIP",
        "devices.media": "SKIP",
    }
    assert "`alphaavatar config init <name> --avatar-id <id>`" in checks["config.load"]["action"]
    assert (
        checks["paths.home"]["summary"] == f"{home}  (not created yet; created when first needed)"
    )
    # Read-only and offline: no file or directory, no client, no local socket.
    assert (files(tmp_path), sandbox) == (before, [])

    # Listing runs nothing, so even unreadable settings cannot stop it.
    (home / "settings").mkdir(parents=True)
    (home / "settings" / "settings.yaml").write_text("default_bundle: [\n")
    assert main(["doctor", "--list", "--json"]) == 0
    assert [spec["id"] for spec in json.loads(capsys.readouterr().out)["checks"]] == IDS
    with pytest.raises(SystemExit) as invalid:
        main(["doctor", "--list", "alpha"])
    assert invalid.value.code == 2


def test_doctor_selects_and_loads_configurations_as_config_check_does(
    tmp_path: Path,
    home: Path,
    sandbox: list[str],
    credentials: object,
    disk: object,
    capsys: pytest.CaptureFixture,
) -> None:
    assert main(["config", "init", "alpha", "--avatar-id", "alpha"]) == 0
    single = write(tmp_path / "single.json", CONFIG | {"avatar": {"id": "single"}})
    capsys.readouterr()
    before = files(tmp_path)
    # The default bundle, a named one, an override alone (default bundle) and a file.
    for argv in ([], ["alpha"], ["avatar.id=renamed"], [str(single), "voice.tts.speed=1.3"]):
        assert main(["config", "check", *argv, "--json"]) == 0
        summary = json.loads(capsys.readouterr().out)
        code, checks, _ = doctor(capsys, *argv)
        source = summary["config"]
        origin = f"bundle {source['bundle']}" if source["bundle"] else f"file {source['file']}"
        origin += " (default)" if source["default"] else ""
        assert code == 0
        assert checks["config.load"]["summary"] == f"{origin} loaded and validated"
        assert checks["config.load"]["details"] == [f"avatar {summary['avatar_id']}"]
        assert checks["paths.workspace"]["summary"].startswith(f"{summary['workspace']}  (")
        assert checks["packages.capabilities"]["status"] == "PASS"
        # What static checks cannot see is reported as not verified, never as passing.
        assert [checks[check]["status"] for check in UNVERIFIED] == ["SKIP"] * 3
    # The file's remote vector store and MCP server are named, though not contacted.
    assert {"Qdrant", "1 MCP server"} <= set(checks["services.external"]["details"])

    # A missing bundle fails as config check fails, with exit code 1 and a next step.
    assert main(["config", "check", "nope"]) == 2
    refused = capsys.readouterr().err
    code, checks, _ = doctor(capsys, "nope")
    assert code == 1 and checks["config.load"]["status"] == "FAIL"
    assert checks["config.load"]["details"][-1] in refused
    assert "Bundle 'nope' does not exist" in checks["config.load"]["details"][-1]
    assert checks["config.load"]["action"]
    assert checks["packages.capabilities"]["status"] == "SKIP"
    assert (files(tmp_path), sandbox) == (before, [])


def test_missing_packages_fail_and_low_disk_space_warns_with_a_next_step(
    home: Path, credentials: object, disk: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    assert main(["config", "init", "alpha", "--avatar-id", "alpha"]) == 0
    capsys.readouterr()
    real = metadata.distribution

    def uninstalled(name: str) -> metadata.Distribution:
        # The RTC extra, and the default provider backend the template's tasks rely on.
        if name.lower() in ("livekit", "langchain-openai"):
            raise metadata.PackageNotFoundError(name)
        return real(name)

    with mock.patch.object(metadata, "distribution", uninstalled):
        code, checks, _ = doctor(capsys)
    assert code == 1
    capabilities = checks["packages.capabilities"]
    assert capabilities["status"] == "FAIL"
    assert capabilities["details"] == [
        "rtc: livekit is not installed",
        "providers: langchain-openai is not installed",
    ]
    assert capabilities["action"] == (
        "Install into this Python environment: "
        "'alpha-avatar-host[livekit]' 'alpha-avatar-plugins-provider[langchain]'"
    )

    disk.free = 1 << 20
    code, checks, _ = doctor(capsys)
    assert code == 0
    assert [checks[check]["status"] for check in PATHS] == ["WARN"] * 3
    assert all(checks[check]["action"] for check in PATHS)


def test_doctor_reports_pass_the_configuration_output_boundary(
    tmp_path: Path, credentials: object, disk: object, capsys: pytest.CaptureFixture
) -> None:
    # A credential reused as the Avatar ID, and terminal escapes in the home and file paths.
    home = tmp_path / "home\x1b[2Jdir"
    value = CONFIG | {"application": {"home": str(home)}, "avatar": {"id": SECRETS["vdb"]}}
    config = write(tmp_path / "avatar\x1b[31m.json", value)
    code, checks, output = doctor(capsys, str(config))
    assert code == 0
    assert checks["config.load"]["details"] == ["avatar [redacted]"]
    assert checks["paths.home"]["details"][0].startswith("chosen by the configuration file;")
    assert "[redacted]" in checks["paths.workspace"]["summary"]
    assert [name for name, secret in SECRETS.items() if secret in output] == []
    assert "\x1b" not in output and "\\u001b" not in output
