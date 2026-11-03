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
"""config check output: summaries, failures, styles and streams, offline and credential safe."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from config_samples import CONFIG, SECRETS, files, write

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.log.format import BOLD, DIM, GREEN, RESET


@pytest.fixture
def color_capable() -> object:
    """Styling assertions must not depend on an inherited NO_COLOR or TERM=dumb."""
    with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}):
        os.environ.pop("NO_COLOR", None)
        yield


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def run_cli(*argv: str, stdout: io.StringIO, stderr: io.StringIO) -> int:
    with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
        return main(list(argv))


def test_check_reports_valid_and_invalid_configurations_with_effective_overrides(
    tmp_path: Path, sandbox: list[str], credentials: object, capsys: pytest.CaptureFixture
) -> None:
    config = write(tmp_path / "avatar.json", CONFIG)
    before = files(tmp_path)

    assert main(["config", "check", str(config), "avatar.id=renamed"]) == 0
    text = capsys.readouterr().out
    assert main(["config", "check", str(config), "avatar.id=renamed", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert text.splitlines() == [
        "",
        "OK  configuration and read-only path checks passed",
        f"    config          {config}",
        "    avatar_id       renamed",
        f"    home            {report['home']}",
        f"    workspace       {report['workspace']}",
        "    host",
        "      rtc           livekit",
        "      health        127.0.0.1:8081 (dev: free port)",
        "    agent",
        f"      inference     {len(report['inference'])} runners, 1 worker each",
        "    plugins/foundation",
        "      context       default",
        "      loop          realtime",
        "      voice         vad=none  stt=none  tts=none",
        "      vision        off",
        "    plugins/perception",
        "      status        default",
        "      router        default  (audio activity on, semantic addressing on, "
        "visual addressing on, turn taking on, interruption on)",
        "      character     none",
        "      memory        default  "
        "(vdb: qdrant; retrieval on, conversation on, tool on, environment off)",
        "      persona       default  (vdb: lancedb; profiler on, speaker on, face on)",
        "    plugins/tools",
        "      deepresearch  default",
        "      rag           default",
        "      mcp           default  (1 server)",
        "",
    ]
    # Selections and backend kinds only: no endpoint, collection or plugin-defined setting.
    assert "invalid" not in text + json.dumps(report)
    # The override is the configuration that would start, including its default workspace.
    assert report.keys() == {
        "valid",
        "config",
        "avatar_id",
        "home",
        "workspace",
        "plugins",
        "inference",
        "health",
    }
    assert report["config"] == {"bundle": None, "default": False, "file": str(config)}
    assert report["valid"] and report["avatar_id"] == "renamed"
    assert report["plugins"]["memory"] == {
        "plugin": "default",
        "vdb": "qdrant",
        "retrieval": True,
        "conversation": True,
        "tool": True,
        "environment": False,
    }
    assert report["plugins"]["tools"]["mcp"] == {"plugin": "default", "servers": 1}
    assert report["health"] == {"bind": "127.0.0.1", "port": None}
    assert report["workspace"] == f"{report['home']}/avatars/renamed"
    # Switches follow the configuration: environment memory and vision, as start would run.
    environment = "memory.init_config.environment"
    switched = (f"{environment}.enabled=true", f"{environment}.provider.task=memory.env_delta")
    switched += ("vision.enabled=true", "vision.input_mode=vlm")
    assert main(["config", "check", str(config), *switched]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "      vision        on  (input: vlm)" in lines
    assert any(line.endswith("tool on, environment on)") for line in lines)

    assert main(["config", "check", str(config), "tools.mcp.token=leak"]) == 2
    output = capsys.readouterr()
    assert output.err.startswith("\nERROR  configuration and read-only path checks failed\n")
    assert output.err.endswith("\n\n")
    assert "fields: tools.mcp.token" in output.err and "leak" not in output.out + output.err
    # A remote store without a port fails the inference plan at startup; loading reports it.
    assert main(["config", "check", str(config), "persona.vdb_config.host=vectors.invalid"]) == 2
    assert "caused by: ValueError\n    at alphaavatar.agents.utils.vdb.config" in (
        capsys.readouterr().err
    )
    assert main(["config", "check", str(config), "avatar.timezone=Not/AZone", "--json"]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["valid"] is False
    assert failure["error"]["fields"] == ["avatar.timezone"]
    assert "Not/AZone" not in json.dumps(failure)

    # No Host, client, socket, child process or workspace: only the input file exists.
    assert (sandbox, files(tmp_path)) == ([], before)


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
@pytest.mark.parametrize(
    "broken",
    [
        {"tools": {"mcp": {"enabled": True, "token": SECRETS["vdb"], "servers": {}}}},
        # The outer Host section: LiveKit settings reject a credential typed into init_config.
        {"host": {"rtc": {"init_config": {"api_secret": SECRETS["vdb"]}}}},
    ],
    ids=["avatar-section", "host-section"],
)
def test_error_output_never_echoes_rejected_values(
    broken: dict, as_json: bool, tmp_path: Path, sandbox: list[str], capsys: pytest.CaptureFixture
) -> None:
    config = write(tmp_path / "avatar.json", {"avatar": {"id": "assistant"}, **broken})
    assert main(["config", "check", str(config), *(["--json"] if as_json else [])]) == 2
    output = capsys.readouterr()
    assert SECRETS["vdb"] not in output.out + output.err
    if as_json:
        error = json.loads(output.out)["error"]
        assert error["type"] == "ValidationError" and error["fields"]
        assert set(error) == {"type", "fields", "diagnostic"}
    else:
        assert "fields: " in output.err
    assert sandbox == []


def test_check_summary_passes_the_same_output_boundary(
    tmp_path: Path, credentials: object, capsys: pytest.CaptureFixture
) -> None:
    # A credential reused as the Avatar ID, and terminal escapes in the home and file paths.
    home = tmp_path / "home\x1b[2Jdir"
    value = CONFIG | {
        "application": {"home": str(home)},
        "avatar": {"id": SECRETS["MCP_DOCS_TOKEN"]},
    }
    config = write(tmp_path / "avatar\x1b[31m.json", value)
    assert main(["config", "check", str(config)]) == 0
    text = capsys.readouterr().out
    assert main(["config", "check", str(config), "--json"]) == 0
    report = capsys.readouterr().out
    summary = json.loads(report)
    assert "    avatar_id       [redacted]" in text.splitlines()
    assert summary["avatar_id"] == "[redacted]"
    assert summary["config"]["file"] == str(tmp_path / "avatar.json")
    assert summary["home"] == str(tmp_path / "homedir") and "[redacted]" in summary["workspace"]
    for output in (text, report):
        assert "\x1b" not in output and "\\u001b" not in output
        assert SECRETS["MCP_DOCS_TOKEN"] not in output


@pytest.mark.parametrize(
    ("terminal", "environment"),
    [(True, {}), (False, {}), (True, {"NO_COLOR": ""}), (True, {"TERM": "dumb"})],
    ids=["terminal", "pipe", "no-color", "dumb-terminal"],
)
def test_only_an_enabled_terminal_gets_styles_and_json_stays_plain(
    terminal: bool, environment: dict[str, str], tmp_path: Path, color_capable: object
) -> None:
    config = write(tmp_path / "avatar.json", {"avatar": {"id": "assistant"}})
    stream = Terminal if terminal else io.StringIO
    styled = terminal and not environment
    with mock.patch.dict(os.environ, environment):
        checked, as_json = stream(), stream()
        assert run_cli("config", "check", str(config), stdout=checked, stderr=stream()) == 0
        assert (
            run_cli("config", "check", str(config), "--json", stdout=as_json, stderr=stream()) == 0
        )

    assert checked.getvalue().startswith(f"\n{BOLD}{GREEN}OK{RESET}  " if styled else "\nOK  ")
    assert checked.getvalue().endswith("\n\n")
    # Labels are auxiliary and dimmed; values keep the default foreground.
    label = "avatar_id".ljust(len("deepresearch") + 2)  # Aligned with the nested labels.
    avatar = f"    {DIM}{label}{RESET}  assistant" if styled else f"    {label}  assistant"
    assert avatar in checked.getvalue().splitlines()
    assert ("\x1b" in checked.getvalue()) == styled
    # JSON never carries terminal styling, even on a terminal.
    assert "\x1b" not in as_json.getvalue() and json.loads(as_json.getvalue())["valid"]
