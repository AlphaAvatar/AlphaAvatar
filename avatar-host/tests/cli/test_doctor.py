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
"""doctor: read-only and offline, config check's selection rules, exit codes, one report.

How complete this machine's installation is belongs to the machine: package checks are only
asserted where a test removes a package itself.
"""

from __future__ import annotations

import json
import os
import shutil
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from config_samples import CONFIG, LOOP, SECRETS, files, write

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.cli.commands.doctor import GROUPS
from alphaavatar.host.doctor import CHECKS, Check, Report

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
    assert code == (1 if report["status"] == "FAIL" else 0)
    lines = text.splitlines()
    # Grouped for reading; a pass is one line, anything else shows its details and next step.
    headings = [line for line in lines if line.startswith("    ") and line[4] != " "]
    assert [heading.strip() for heading in headings] == list(GROUPS)
    for check in report["checks"]:
        heading = f"{check['status']}  {check['id'].ljust(21)}  {check['summary']}"
        assert f"      {heading}" in lines
        shown = [line.strip() in check["details"] for line in lines]
        assert any(shown) == (check["status"] != "PASS" and bool(check["details"]))
    return code, {check["id"]: check for check in report["checks"]}, text + raw


def test_without_a_configuration_doctor_says_how_to_create_one_and_checks_the_rest(
    tmp_path: Path, home: Path, sandbox: list[str], disk: object, capsys: pytest.CaptureFixture
) -> None:
    before = files(tmp_path)
    _, checks, _ = doctor(capsys)
    # A missing configuration warns; everything that needs none is still checked.
    statuses = {check: report["status"] for check, report in checks.items()}
    assert statuses.pop("packages.alphaavatar") != "SKIP"
    assert statuses == {
        "system.platform": "PASS",
        "python.version": "PASS",
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
    # Warnings and unverified checks never fail a report; one failed check does.
    assert Report((Check("a", "WARN", "a"), Check("b", "SKIP", "b"))).exit_code == 0
    assert Report((Check("a", "PASS", "a"), Check("b", "FAIL", "b"))).exit_code == 1

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
        _, checks, _ = doctor(capsys, *argv)
        source = summary["config"]
        origin = f"bundle {source['bundle']}" if source["bundle"] else f"file {source['file']}"
        origin += " (default)" if source["default"] else ""
        assert checks["config.load"]["summary"] == f"{origin} loaded and validated"
        assert checks["config.load"]["details"] == [f"avatar {summary['avatar_id']}"]
        assert checks["paths.workspace"]["summary"].startswith(f"{summary['workspace']}  (")
        # What static checks cannot see is reported as not verified, never as passing.
        assert [checks[check]["status"] for check in UNVERIFIED] == ["SKIP"] * 3
    # The file's remote vector store and MCP server are named, though not contacted.
    assert {"Qdrant", "1 MCP server"} <= set(checks["services.external"]["details"])

    # Refusals match config check's, including a built-in plugin's own schema, with exit 1.
    no_model = write(tmp_path / "no-model.json", CONFIG | {"loop": {"plugin": "realtime"}})
    before = files(tmp_path)
    for argv in (["nope"], ["alpha", "persona.init_config.unknown=1"], [str(no_model)]):
        assert main(["config", "check", *argv]) == 2
        refused = capsys.readouterr().err
        code, checks, _ = doctor(capsys, *argv)
        assert code == 1 and checks["config.load"]["status"] == "FAIL"
        assert all(line in refused for line in checks["config.load"]["details"])
        assert checks["config.load"]["action"]
        assert checks["packages.capabilities"]["status"] == "SKIP"
    assert "fields: loop.init_config.model" in checks["config.load"]["details"]
    assert (files(tmp_path), sandbox) == (before, [])

    # Unreadable settings do not stop a named bundle; the home check says what to fix.
    settings = home / "settings" / "settings.yaml"
    settings.write_text("default_bundle: [\n")
    _, checks, _ = doctor(capsys, "alpha")
    assert checks["config.load"]["status"] == "PASS"
    assert checks["paths.home"]["status"] == "WARN"
    assert checks["paths.home"]["action"].startswith(f"Fix or remove {settings};")


def test_provider_backends_follow_defaults_and_skip_what_start_does_not_create(
    tmp_path: Path, credentials: object, disk: object, capsys: pytest.CaptureFixture
) -> None:
    without_mcp = CONFIG["tools"] | {"mcp": {"enabled": False}}

    def providers(model: dict, **sections: object) -> tuple[list[str], dict[str, dict]]:
        loop = {"plugin": "realtime", "init_config": {"model": model}}
        value = CONFIG | {"loop": loop, "tools": without_mcp} | sections
        _, checks, _ = doctor(capsys, str(write(tmp_path / "avatar.json", value)))
        found = checks["services.external"]["details"]
        return [line for line in found if line.startswith("model providers")], checks

    # The loop alone: memory and persona from another plugin add no store embeddings.
    others = {"memory": {"plugin": "custom"}, "persona": {"plugin": "custom"}}
    # A task naming only its model takes the schema's defaults, as if they were written out.
    implicit, _ = providers({"model": "m"}, **others)
    explicit, _ = providers({"model": "m", "backend": "langchain", "provider": "openai"}, **others)
    assert implicit == explicit == ["model providers (langchain)"]
    # The store embeddings alone: the loop names another backend; they use the default.
    assert providers({"model": "m", "backend": "openai"})[0] == [
        "model providers (langchain, openai)"
    ]
    # Switched-off processors and disabled tools are not created: their leftovers need nothing.
    leftover = {"tasks": {"leftover": {"model": "m", "backend": "nowhere"}}}
    off = {"enabled": False, "provider": {"gateway": leftover}}
    memory = CONFIG["memory"] | {"init_config": {"tool": off}}
    persona = {"init_config": {"profiler": off}}
    rag = {"plugin": None, "init_config": {"summary": {"model": "m", "backend": "nowhere"}}}
    found, checks = providers(
        LOOP["init_config"]["model"],
        memory=memory,
        persona=persona,
        tools=without_mcp | {"rag": rag},
    )
    assert found == ["model providers (langchain)"]
    assert not any("nowhere" in line for line in checks["packages.capabilities"]["details"])


def test_missing_packages_unusable_paths_and_env_files_fail_with_a_next_step(
    tmp_path: Path,
    home: Path,
    credentials: object,
    disk: SimpleNamespace,
    capsys: pytest.CaptureFixture,
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
    capabilities = checks["packages.capabilities"]
    assert code == 1 and capabilities["status"] == "FAIL"
    assert {"rtc: livekit is not installed", "providers: langchain-openai is not installed"} <= set(
        capabilities["details"]
    )
    # Other packages missing on this machine may be named too.
    assert "'alpha-avatar-host[livekit]'" in capabilities["action"]
    assert "'alpha-avatar-plugins-provider[langchain]'" in capabilities["action"]

    # Low free space warns.
    disk.free = 1 << 20
    _, checks, _ = doctor(capsys)
    assert [checks[check]["status"] for check in PATHS] == ["WARN"] * 3
    assert all(checks[check]["action"] for check in PATHS)

    # A home behind a link without a target cannot be created: it fails, not passes.
    disk.free = 64 << 30
    shutil.move(home, tmp_path / "moved")
    home.symlink_to(tmp_path / "missing")
    code, checks, _ = doctor(capsys)
    assert code == 1
    assert [checks[check]["status"] for check in ("paths.home", "paths.cache")] == ["FAIL"] * 2
    assert checks["paths.home"]["summary"] == f"{home} is a symbolic link that does not resolve"
    assert checks["paths.cache"]["action"]

    # An unreadable .env is reported in the same machine-readable report.
    env_file = tmp_path / "broken.env"
    env_file.write_bytes(b"OPENAI_API_KEY=\xff\xfe\n")
    with mock.patch.dict(os.environ, {"ENV_FILE": str(env_file)}):
        code, checks, output = doctor(capsys)
    assert code == 1
    load = checks["config.load"]
    assert (load["status"], load["summary"]) == ("FAIL", "The environment file could not be read")
    assert load["details"][0] == "error: UnicodeDecodeError"
    assert load["action"].startswith("Fix the file ENV_FILE names")
    assert [checks[check]["status"] for check in PATHS] == ["SKIP"] * 3
    assert "Traceback" not in output


def test_doctor_reports_pass_the_configuration_output_boundary(
    tmp_path: Path, credentials: object, disk: object, capsys: pytest.CaptureFixture
) -> None:
    # A credential reused as the Avatar ID, and terminal escapes in the home and file paths.
    home = tmp_path / "home\x1b[2Jdir"
    value = CONFIG | {"application": {"home": str(home)}, "avatar": {"id": SECRETS["vdb"]}}
    config = write(tmp_path / "avatar\x1b[31m.json", value)
    _, checks, output = doctor(capsys, str(config))
    assert checks["config.load"]["details"] == ["avatar [redacted]"]
    assert checks["paths.home"]["details"][0].startswith("chosen by the configuration file;")
    assert "[redacted]" in checks["paths.workspace"]["summary"]
    assert [name for name, secret in SECRETS.items() if secret in output] == []
    assert "\x1b" not in output and "\\u001b" not in output
