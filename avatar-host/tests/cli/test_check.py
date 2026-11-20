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
"""config init and config check output: summaries, failures, styles and streams, offline and
credential safe."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from config_samples import CONFIG, LOOP, SECRETS, files, write

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.log.format import BOLD, BRAND_BLUE, GREEN, RESET


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

    # Wider than any path can be (O-22): where a narrow terminal wraps is the renderer's own test.
    with mock.patch.dict(os.environ, {"COLUMNS": "10000"}):
        assert main(["config", "check", str(config), "avatar.id=renamed"]) == 0
    text = capsys.readouterr().out
    assert main(["config", "check", str(config), "avatar.id=renamed", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert text.splitlines() == [
        "",
        "AlphaAvatar / Config check",
        "OK    Configuration and read-only path checks passed",
        "",
        "Configuration",
        f"  config         {config}",
        "  avatar_id      renamed",
        f"  home           {report['home']}",
        f"  workspace      {report['workspace']}",
        "",
        "host",
        "  rtc            livekit",
        "  health         127.0.0.1:8081 (dev: free port)",
        "",
        "agent",
        f"  inference      {len(report['inference'])} runners, 1 worker each",
        "",
        "plugins/foundation",
        "  context        default",
        "  loop           realtime",
        "  voice          vad=none  stt=none  tts=none",
        "  vision         off",
        "",
        "plugins/perception",
        "  status         default",
        "  router         default  (audio activity on, semantic addressing on, "
        "visual addressing on, turn taking on, interruption on)",
        "  character      none",
        "  memory         default  "
        "(vdb: qdrant; retrieval on, conversation on, tool on, environment off)",
        "  persona        default  (vdb: lancedb; profiler on, speaker on, face on)",
        "",
        "plugins/tools",
        "  deepresearch   default",
        "  rag            default",
        "  mcp            default  (1 server)",
        "",
    ]
    # Selections and backend kinds only: no service URL, collection or plugin-defined setting.
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
    with mock.patch.dict(os.environ, {"COLUMNS": "200"}):
        assert main(["config", "check", str(config), *switched]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "  vision         on  (input: vlm)" in lines
    assert any(line.endswith("tool on, environment on)") for line in lines)

    assert main(["config", "check", str(config), "tools.mcp.token=leak"]) == 2
    output = capsys.readouterr()
    assert output.err.startswith(
        "\nAlphaAvatar / Config check\nERROR Configuration and read-only path checks failed\n\n"
    )
    assert output.out == ""  # The result goes to stderr alone.
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
        assert set(error) == {"type", "fields", "diagnostic", "problems", "action"}
    else:
        assert "fields: " in output.err
    assert sandbox == []


MCP = """deepresearch: {plugin: null}
rag: {plugin: null}
mcp:
  plugin: default
  enabled: true
  servers:
    docs:
      url: https://mcp.invalid/
      headers: {Authorization: Bearer <MCP_PAT>, X-Seen: inline-value}
    code:
      url: https://code.invalid/
      headers: {Authorization: "Bearer ${oc.env:GITHUB_PAT}", X-Region: "${oc.env:REGION}"}
"""


def test_a_variable_holding_no_value_is_named_at_the_setting_that_reads_it(
    tmp_path: Path, home: Path, sandbox: list[str], capsys: pytest.CaptureFixture
) -> None:
    """The credentials an MCP server reads, by placeholder or in Authorization, and an
    ordinary interpolated variable: each named with the setting that reads it, in config
    check's text and JSON and in Doctor's config.load, with the same next step; never a value
    as written, nor a validation message."""
    assert main(["config", "init", "alpha", "--avatar-id", "alpha"]) == 0
    capsys.readouterr()
    (home / "configs/profiles/alpha/plugins/tools/tools.yaml").write_text(MCP)
    env_file = tmp_path / "chosen.env"
    env_file.write_text("")
    environ = {"ENV_FILE": str(env_file), "COLUMNS": "1000"}
    shown = []

    def check(*argv: str) -> tuple[str, dict]:
        assert main(["config", "check", *argv]) == 2
        text = capsys.readouterr().err
        assert main(["config", "check", *argv, "--json"]) == 2
        failure = json.loads(capsys.readouterr().out)["error"]
        assert main(["doctor", *argv, "--no-metrics", "--json"]) == 1
        load = {c["id"]: c for c in json.loads(capsys.readouterr().out)["checks"]}["config.load"]
        # Doctor says what config check says, with the same next step.
        assert all(f"      {line}" in text for line in load["details"][2:])
        assert [p["line"] for p in failure["problems"]] == load["details"][2:]
        assert load["action"] == failure["action"]
        shown.append(text + json.dumps(failure) + json.dumps(load))
        return text, failure

    names = ("MCP_PAT", "GITHUB_PAT", "REGION")
    with mock.patch.dict(os.environ, environ), mock.patch("sys.stdin.isatty", return_value=False):
        for name in names:
            os.environ.pop(name, None)
        # Interpolated first: the Authorization credential, the .env file and the stored ones
        # consulted too, and an ordinary variable, which only its default would stand for.
        text, failure = check()
        code = "tools.mcp.servers.code.headers"
        assert (
            f"      {code}.Authorization reads the credential GITHUB_PAT, which is not set" in text
        )
        region = (
            f"{code}.X-Region reads REGION, which is not set, and ${{oc.env:REGION}} has no default"
        )
        assert f"      {region}" in text
        assert failure["type"] == "MissingVariables"
        assert failure["fields"] == [f"{code}.Authorization", f"{code}.X-Region"]
        assert [p["variable"] for p in failure["problems"]] == ["GITHUB_PAT", "REGION"]
        assert failure["action"].startswith(
            "Set GITHUB_PAT, REGION in the environment or in the .env"
        )
        # The credential blank in the process, where no source holds one, is refused too, never
        # sent as "Bearer "; the ordinary variable set empty interpolates as empty.
        os.environ.update({"GITHUB_PAT": " ", "REGION": ""})
        text, failure = check()
        assert f"      {code}.Authorization reads the credential GITHUB_PAT, which is empty" in text
        assert failure["type"] == "MissingVariables"
        assert failure["fields"] == [f"{code}.Authorization"]
        assert failure["action"].startswith("Set GITHUB_PAT in the environment or in the .env")
        # Then validation's: a placeholder, unset, then empty; one set empty interpolates.
        env_file.write_text("GITHUB_PAT=fictional-file-github\n")
        os.environ["REGION"] = ""
        docs = "tools.mcp.servers.docs.headers.Authorization"
        text, failure = check()
        assert f"      {docs} reads the credential MCP_PAT, which is not set" in text
        assert failure["problems"] == [
            {
                "line": f"{docs} reads the credential MCP_PAT, which is not set",
                "location": docs,
                "problem": "reads the credential MCP_PAT, which is not set",
                "package": None,
                "action": None,
                "variable": "MCP_PAT",
            }
        ]
        os.environ["MCP_PAT"] = "  "
        text, _ = check()
        assert f"      {docs} reads the credential MCP_PAT, which is empty" in text
        # With another field refused: both, that one by its path alone.
        text, failure = check("alpha", "avatar.timezone=Not/AZone")
        assert failure["fields"] == ["avatar.timezone", docs]
        assert "      avatar.timezone is not valid" in text
        assert failure["action"].endswith(", and fix the other fields")
    output = "".join(shown)
    for value in ("Bearer", "inline-value", "mcp.invalid", "fictional-file-github", "Not/AZone"):
        assert value not in output
    assert "Value error" not in output and "is required in config" not in output
    assert sandbox == []


def test_escaped_interpolation_reads_nothing_and_a_failing_one_keeps_its_setting(
    tmp_path: Path, home: Path, sandbox: list[str], capsys: pytest.CaptureFixture
) -> None:
    """``\\${oc.env:NAME}`` is text, as OmegaConf escapes it: it loads as written and is never
    taken for a variable to set. An interpolation that fails beside it is named at its setting,
    in config check and Doctor alike, with any variable that holds no value."""
    from alphaavatar.host.configs import load_application

    config = tmp_path / "escaped.yaml"
    loop = f"loop: {json.dumps(LOOP)}\n"
    escaped = r"Use template \${oc.env:LITERAL_NAME}"

    def check(text: str) -> tuple[str, dict]:
        config.write_text(loop + text)
        assert main(["config", "check", str(config)]) == 2
        shown = capsys.readouterr().err
        assert main(["config", "check", str(config), "--json"]) == 2
        failure = json.loads(capsys.readouterr().out)["error"]
        assert main(["doctor", str(config), "--no-metrics", "--json"]) == 1
        load = {c["id"]: c for c in json.loads(capsys.readouterr().out)["checks"]}["config.load"]
        assert [p["line"] for p in failure["problems"]] == load["details"][2:]
        assert load["action"] == failure["action"]
        for name in ("LITERAL_NAME", "DEFAULTED_NAME"):
            assert name not in shown + json.dumps(failure) + json.dumps(load)
        return shown, failure

    timezone = "avatar.timezone holds an interpolation that cannot be resolved"
    with mock.patch.dict(os.environ, {"COLUMNS": "1000"}):
        for name in ("LITERAL_NAME", "REAL_NAME", "DEFAULTED_NAME"):
            os.environ.pop(name, None)
        config.write_text(f"{loop}avatar:\n  id: alpha\n  introduction: '{escaped}'\n")
        loaded = load_application(config)
        assert loaded.avatar.avatar.introduction == "Use template ${oc.env:LITERAL_NAME}"
        # As written: the escaped text first, the failing interpolation after it.
        text, failure = check(
            f"avatar:\n  id: alpha\n  introduction: '{escaped}'\n  timezone: '${{not_a_setting}}'\n"
        )
        assert f"      {timezone}" in text
        assert failure["type"] == "ConfigProblems" and failure["fields"] == ["avatar.timezone"]
        # Beside a variable an even run of backslashes leaves read, both, by their settings;
        # one unset with a default takes it.
        text, failure = check(
            "avatar:\n  id: alpha\n  timezone: '${not_a_setting}'\n"
            f"  introduction: '{escaped} and \\\\${{oc.env:REAL_NAME}}"
            " ${oc.env:DEFAULTED_NAME,kept}'\n"
        )
        assert failure["type"] == "MissingVariables"
        assert failure["fields"] == ["avatar.introduction", "avatar.timezone"]
        assert [p["variable"] for p in failure["problems"]] == ["REAL_NAME", None]
        assert f"      {timezone}" in text
        assert failure["action"].endswith(", and fix the other fields")
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
    assert "  avatar_id      [redacted]" in text.splitlines()
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
    config = write(tmp_path / "avatar.json", {"avatar": {"id": "assistant"}, "loop": LOOP})
    stream = Terminal if terminal else io.StringIO
    styled = terminal and not environment
    with mock.patch.dict(os.environ, environment):
        checked, as_json = stream(), stream()
        assert run_cli("config", "check", str(config), stdout=checked, stderr=stream()) == 0
        assert (
            run_cli("config", "check", str(config), "--json", stdout=as_json, stderr=stream()) == 0
        )

    # The title in brand blue, the status in its color; the rest in the default foreground.
    title = (
        f"{BRAND_BLUE}AlphaAvatar / Config check{RESET}" if styled else "AlphaAvatar / Config check"
    )
    ok = f"{GREEN}OK{RESET}    " if styled else "OK    "
    assert checked.getvalue().startswith(f"\n{title}\n{ok}Configuration and read-only")
    assert checked.getvalue().endswith("\n\n")
    lines = checked.getvalue().splitlines()
    # Group headings are bold; labels and values are not styled at all.
    assert (f"{BOLD}plugins/tools{RESET}" if styled else "plugins/tools") in lines
    assert f"  {'avatar_id'.ljust(len('deepresearch') + 3)}assistant" in lines
    assert ("\x1b" in checked.getvalue()) == styled
    # JSON never carries terminal styling, even on a terminal.
    assert "\x1b" not in as_json.getvalue() and json.loads(as_json.getvalue())["valid"]


@pytest.mark.parametrize("bare", [False, True], ids=["installed", "bare-package"])
def test_init_reports_the_bundle_its_credentials_by_name_and_what_to_run_next(
    bare: bool, capsys: pytest.CaptureFixture
) -> None:
    from alphaavatar.host.cli.commands import config as command
    from alphaavatar.host.cli.render import home_relative

    argv = ["config", "init", "my-avatar", "--avatar-id", "my-avatar"]
    with (
        mock.patch.object(command, "_bare_package", return_value=bare),
        mock.patch.dict(os.environ, {"COLUMNS": "200"}),
    ):
        assert main(argv) == 0
    output = capsys.readouterr()
    profiles = Path.home() / ".local/share/alphaavatar/configs/profiles/my-avatar"
    # What the installation can run next: in a bare package, setting this bundle up; else
    # checking, then diagnosing it, before anything starts. Each command on its own line.
    upcoming = ["alphaavatar setup my-avatar"]
    if not bare:
        upcoming = ["alphaavatar config check my-avatar", "alphaavatar doctor my-avatar"]
    assert output.out.splitlines() == [
        "",
        "AlphaAvatar / Config init",
        "OK    Bundle created",
        "",
        "Configuration",
        "  Bundle       my-avatar",
        f"  Profiles     {home_relative(profiles)}",
        "  Default      my-avatar",
        "",
        "Required credentials",
        "  OPENAI_API_KEY",
        "  LIVEKIT_URL · LIVEKIT_API_KEY · LIVEKIT_API_SECRET",
        "",
        "Next",
        *(f"  {command}" for command in upcoming),
        "",
    ]
    assert output.err == ""
    # Again: refused on stderr, naming the file it would not overwrite; nothing on stdout.
    assert main(argv) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("\nAlphaAvatar / Config init\nERROR Refusing to overwrite")
    assert "configs/bundles/my-avatar.yaml" in output.err
