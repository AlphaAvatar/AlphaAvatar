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
"""Console entry points: import cost, credential-free errors and the converged commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from config_samples import LAYOUT

# Base CLI commands must not need models, providers, transports or avatar configuration.
FORBIDDEN_IMPORTS = (
    "torch",
    "numpy",
    "openai",
    "qdrant_client",
    "llama_cpp",
    "livekit",
    "omegaconf",
    "alphaavatar.plugins",
    "alphaavatar.agents.configs",
)


IMPORT_PROBE = """
import contextlib, io, json, sys
from alphaavatar.host.cli.app import main
for argv in (["--help"], ["--version"]):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.suppress(SystemExit):
        main(argv)
forbidden = tuple(sys.argv[1:])
print(json.dumps(sorted(
    name for name in sys.modules if any(name == f or name.startswith(f + ".") for f in forbidden)
)))
"""


# The CLI where the named modules are not installed: plugin packages left out of an install,
# or WeasyPrint, which fails to import without the system's Pango.
UNINSTALLED = """
import importlib.abc, json, sys
class Uninstalled(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "weasyprint" or name.startswith(tuple(sys.argv[2:])):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
sys.meta_path.insert(0, Uninstalled())
from alphaavatar.host.cli.app import main
sys.exit(main(json.loads(sys.argv[1])))
"""


def files_under(root: Path) -> list[Path]:
    return sorted(path.relative_to(root) for path in root.rglob("*"))


def test_base_cli_needs_no_models_credentials_or_workspace(tmp_path: Path) -> None:
    entrypoint = Path(sys.executable).with_name("alphaavatar")
    assert entrypoint.is_file(), f"Console script is not installed beside {sys.executable}"
    before = files_under(tmp_path)
    # The probe runs --help and --version in-process; the console script's --help exit code
    # and command structure are checked with the converged commands below.
    completed = subprocess.run(
        [str(entrypoint), "--version"], capture_output=True, text=True, timeout=60, env=os.environ
    )
    assert completed.returncode == 0, completed.stderr

    probe = subprocess.run(
        [sys.executable, "-c", IMPORT_PROBE, *FORBIDDEN_IMPORTS],
        capture_output=True,
        text=True,
        timeout=60,
        env=os.environ,
    )
    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout.splitlines()[-1]) == []
    assert files_under(tmp_path) == before


def test_rejected_configuration_secret_never_reaches_cli_output(tmp_path: Path) -> None:
    secret = "sk-fictional-mcp-secret-0042"
    config = tmp_path / "avatar.json"
    config.write_text(
        json.dumps(
            {
                "application": {"home": str(tmp_path / "application")},
                "avatar": {"id": "assistant"},
                "tools": {"mcp": {"enabled": True, "token": secret, "servers": {}}},
            }
        )
    )
    entrypoint = Path(sys.executable).with_name("alphaavatar")
    # dev prints detailed diagnostics; neither stream may echo the rejected value.
    completed = subprocess.run(
        [str(entrypoint), "dev", str(config)],
        capture_output=True,
        text=True,
        timeout=120,
        env=os.environ,
    )
    assert completed.returncode == 2, completed.stderr
    output = completed.stdout + completed.stderr
    assert "fields: tools.mcp.token" in output
    assert secret not in output
    assert not (tmp_path / "application").exists()


def test_init_needs_no_plugin_and_check_names_each_missing_one_where_it_is_selected() -> None:
    def run(argv: list[str], *uninstalled: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", UNINSTALLED, json.dumps(argv), *uninstalled],
            capture_output=True,
            text=True,
            timeout=120,
            env=os.environ,
        )

    def missing(completed: subprocess.CompletedProcess[str]) -> list[str]:
        assert completed.returncode == 2, completed.stderr
        assert "Selected plugins are not installed" in completed.stderr
        return [line.strip() for line in completed.stderr.splitlines() if ": alpha-avatar-" in line]

    # Writing the reference bundle imports no plugin, and not WeasyPrint either.
    created = run(["config", "init", "lean", "--avatar-id", "lean"], "alphaavatar.plugins.")
    assert created.returncode == 0, created.stderr
    # Checking it names every selection of a missing plugin, before importing any of them.
    assert missing(run(["config", "check"], "alphaavatar.plugins.")) == [
        "context.plugin: alpha-avatar-plugins-context",
        "loop.plugin: alpha-avatar-plugins-loop",
        "voice.vad.plugin: alpha-avatar-plugins-voice",
        "voice.stt.plugin: alpha-avatar-plugins-voice",
        "voice.tts.plugin: alpha-avatar-plugins-voice",
        "status.plugin: alpha-avatar-plugins-status",
        "memory.plugin: alpha-avatar-plugins-memory",
        "persona.plugin: alpha-avatar-plugins-persona",
        "router.plugin: alpha-avatar-plugins-router",
    ]
    # One package left out: only what selects it is named; switched off, it is not needed.
    router = "alphaavatar.plugins.router"
    assert missing(run(["config", "check"], router)) == [
        "router.plugin: alpha-avatar-plugins-router"
    ]
    checked = run(["config", "check", "character.plugin=airi"], "alphaavatar.plugins.character")
    assert missing(checked) == ["character.plugin: alpha-avatar-plugins-character"]
    # Sections always built need their package whichever plugin they name, status even while
    # its events are off.
    checked = run(["config", "check", "status.enabled=false"], "alphaavatar.plugins.status")
    assert missing(checked) == ["status.plugin: alpha-avatar-plugins-status"]
    checked = run(["config", "check", "persona.plugin=custom"], "alphaavatar.plugins.persona")
    assert missing(checked) == ["persona.plugin: alpha-avatar-plugins-persona"]
    voiceless = [f"voice.{part}.plugin=null" for part in ("vad", "stt", "tts")]
    checked = run(["config", "check", *voiceless], "alphaavatar.plugins.voice")
    assert checked.returncode == 0, checked.stderr


def test_console_commands_run_without_the_host_log_socket(tmp_path: Path) -> None:
    entrypoint = Path(sys.executable).with_name("alphaavatar")
    home = tmp_path / "home" / ".local" / "share" / "alphaavatar"  # The platform default.

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(entrypoint), *argv], capture_output=True, text=True, timeout=120, env=os.environ
        )

    assert run("config", "init", "console", "--avatar-id", "console").returncode == 0
    for argv in (["console"], []):  # By name, then as the default bundle.
        checked = run("config", "check", *argv, "--json")
        assert checked.returncode == 0, checked.stderr
        report = json.loads(checked.stdout)
        assert (report["avatar_id"], report["config"]["bundle"]) == ("console", "console")
    doctored = run("doctor", "console", "--json")  # Static: it adds nothing to the home.
    assert doctored.returncode == 0, doctored.stderr
    assert json.loads(doctored.stdout)["counts"]["FAIL"] == 0
    configuration = sorted(
        str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()
    )
    assert configuration == sorted(
        [
            "configs/bundles/console.yaml",
            *(f"configs/profiles/console/{path}.yaml" for path in LAYOUT.values()),
            "settings/.write.lock",
            "settings/settings.yaml",
        ]
    )
    # start and dev select alike: a missing bundle fails before anything is created.
    started = run("start", "absent")
    assert started.returncode == 2
    assert "Bundle 'absent' does not exist" in started.stdout + started.stderr
    # The preflight validates built-in plugins' settings as config check does.
    no_model = tmp_path / "no-model.json"
    no_model.write_text(json.dumps({"avatar": {"id": "console"}, "loop": {"plugin": "realtime"}}))
    started = run("start", str(no_model))
    assert started.returncode == 2
    assert "fields: loop.init_config.model" in started.stdout + started.stderr
    # And checks the selected capabilities, as config check does, before preparing anything.
    started = run("start", "console", "persona.plugin=custom")
    assert started.returncode == 2
    assert "persona.plugin: no avatar.perception.persona factory 'custom'" in started.stderr
    assert sorted(path.name for path in home.iterdir()) == ["configs", "settings"]
    # Only the converged commands exist; the removed entry points are usage errors.
    assert run("check", "console").returncode == 2
    assert run("config", "show", "console").returncode == 2
    helped = run("--help")
    assert helped.returncode == 0, helped.stderr
    assert "{dev,start,config,setup,doctor}" in helped.stdout  # No top-level check.
    assert "{init,check}" in run("config", "--help").stdout
