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
"""config init / config check: offline, side-effect free and credential safe."""

from __future__ import annotations

import errno
import io
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from unittest import mock

import lancedb
import pytest
import qdrant_client
import yaml

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.configs import describe_application, load_application
from alphaavatar.host.log.format import BOLD, DIM, GREEN, RED, RESET
from alphaavatar.plugins.memory.config import DefaultMemoryConfig
from alphaavatar.plugins.persona.config import DefaultPersonaConfig

SECRETS = {
    "MCP_DOCS_TOKEN": "tok-fictional-0042",
    "vdb": "vdb-fictional-0042",
    "url": "pw-fictional-0042",
    "query": "q-fictional-0042",
    "OPENAI_API_KEY": "sk-openai-fictional-0042",
}
CONFIG = {
    "avatar": {"id": "assistant", "introduction": f"Uses {SECRETS['vdb']} inline."},
    "memory": {"vdb_config": {"url": "https://vectors.invalid", "api_key": SECRETS["vdb"]}},
    "tools": {
        "mcp": {
            "enabled": True,
            "servers": {
                "docs": {
                    "url": f"https://user:{SECRETS['url']}@mcp.invalid/x?key={SECRETS['query']}",
                    "headers": {"Authorization": "Bearer <MCP_DOCS_TOKEN>"},
                }
            },
        }
    },
}


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Refuse service clients and local sockets, as a restricted review host would."""
    refused: list[str] = []
    real = socket.socket

    def record(name: str):
        def refuse(*args: object, **kwargs: object) -> None:
            refused.append(name)
            raise AssertionError(f"{name} constructed by a configuration command")

        return refuse

    def local_socket(family: int = -1, *args: object, **kwargs: object) -> socket.socket:
        if family == socket.AF_UNIX:
            refused.append("AF_UNIX")
            raise PermissionError(errno.EPERM, "Operation not permitted")
        return real(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", local_socket)
    monkeypatch.setattr(qdrant_client.QdrantClient, "__init__", record("QdrantClient"))
    monkeypatch.setattr(qdrant_client.AsyncQdrantClient, "__init__", record("AsyncQdrantClient"))
    monkeypatch.setattr(lancedb, "connect", record("lancedb.connect"))
    return refused


@pytest.fixture
def credentials() -> object:
    # Restored before the isolation guard compares the process environment.
    with mock.patch.dict(os.environ, {k: v for k, v in SECRETS.items() if k.isupper()}):
        yield


def write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value))
    return path


def files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


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
        "    avatar_id  renamed",
        f"    home       {report['home']}",
        f"    workspace  {report['workspace']}",
        "    rtc        livekit",
        "    loop       realtime",
        "    voice      vad=none  stt=none  tts=none",
        "    router     default",
        "    character  none",
        "    memory     default  (vdb: qdrant)",
        "    persona    default  (vdb: lancedb; speaker on, face on)",
        "    tools      deepresearch, rag, mcp (1 server)",
        "    health     127.0.0.1:8081 (dev: free port)",
        "",
    ]
    # Selections and backend kinds only: no endpoint, collection or plugin-defined setting.
    assert "invalid" not in text + json.dumps(report)
    # The override is the configuration that would start, including its default workspace.
    assert report.keys() == {"valid", "avatar_id", "home", "workspace", "plugins", "health"}
    assert report["valid"] and report["avatar_id"] == "renamed"
    assert report["plugins"]["memory"] == {"plugin": "default", "vdb": "qdrant"}
    assert report["plugins"]["tools"]["mcp"] == {"plugin": "default", "servers": 1}
    assert report["health"] == {"bind": "127.0.0.1", "port": None}
    assert report["workspace"] == f"{report['home']}/avatars/renamed"

    assert main(["config", "check", str(config), "tools.mcp.token=leak"]) == 2
    output = capsys.readouterr()
    assert output.err.startswith("\nERROR  configuration and read-only path checks failed\n")
    assert output.err.endswith("\n\n")
    assert "fields: tools.mcp.token" in output.err and "leak" not in output.out + output.err
    # A remote store without a port fails at startup, so the check reports it first.
    assert main(["config", "check", str(config), "persona.vdb_config.host=vectors.invalid"]) == 2
    assert "error: ValueError" in capsys.readouterr().err
    assert main(["config", "check", str(config), "avatar.timezone=Not/AZone", "--json"]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["valid"] is False
    assert failure["error"]["fields"] == ["avatar.timezone"]
    assert "Not/AZone" not in json.dumps(failure)

    # No Host, client, socket, child process or workspace: only the input file exists.
    assert (sandbox, files(tmp_path)) == ([], before)


def test_safe_projection_keeps_useful_settings_without_credentials(
    tmp_path: Path, sandbox: list[str], credentials: object
) -> None:
    # Over the 8192-character log bound; plugin mappings may carry hostile keys too.
    introduction = "Keep [bold red]this[/] and [hidden] literal: " + "word " * 1800 + "end"
    value = CONFIG | {
        "avatar": {"id": "assistant", "introduction": f"{introduction} {SECRETS['vdb']}\x1b[31m"},
        "context": {"init_config": {"key\x1b[2J": 1}},
    }
    config = load_application(
        write(tmp_path / "avatar.json", value), ["voice.tts.speed=1.3", "loop.plugin=realtime"]
    )
    view = describe_application(config)
    text = json.dumps(view)

    # Useful, non-sensitive facts stay: selections, parameters, overrides and resolved paths.
    assert (view["voice"]["tts"]["speed"], view["loop"]["plugin"]) == (1.3, "realtime")
    assert view["avatar"]["workspace_root"] == str(config.workspace.root)
    assert view["memory"]["vdb_config"] == {"url": "[hidden]", "api_key": "[hidden]"}
    assert view["tools"]["mcp"]["servers"]["docs"]["headers"] == {"Authorization": "[hidden]"}
    # Complete text, a reused credential replaced and terminal escapes removed, keys included.
    assert view["avatar"]["introduction"] == f"{introduction} [redacted]"
    assert view["context"]["init_config"] == {"key": 1}
    assert [name for name, secret in SECRETS.items() if secret in text] == []
    assert "\\u001b" not in text and yaml.safe_load(yaml.safe_dump(view)) == view
    assert sandbox == []


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
    assert (
        text.splitlines()[2] == "    avatar_id  [redacted]" and summary["avatar_id"] == "[redacted]"
    )
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
    terminal: bool, environment: dict[str, str], tmp_path: Path
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
    avatar = f"    {DIM}avatar_id{RESET}  assistant" if styled else "    avatar_id  assistant"
    assert checked.getvalue().splitlines()[2] == avatar
    assert ("\x1b" in checked.getvalue()) == styled
    # JSON never carries terminal styling, even on a terminal.
    assert "\x1b" not in as_json.getvalue() and json.loads(as_json.getvalue())["valid"]


@pytest.mark.parametrize("terminal", ["stdout", "stderr"])
def test_each_stream_detects_its_own_terminal(terminal: str, tmp_path: Path) -> None:
    good = write(tmp_path / "good.json", {"avatar": {"id": "assistant"}})
    bad = write(tmp_path / "bad.json", {"avatar": {"id": "assistant", "timezone": "Not/AZone"}})
    streams = {"stdout": Terminal(), "stderr": io.StringIO()}
    if terminal == "stderr":
        streams = {"stdout": io.StringIO(), "stderr": Terminal()}
    assert run_cli("config", "check", str(good), **streams) == 0
    assert run_cli("config", "check", str(bad), **streams) == 2
    out, err = streams["stdout"].getvalue(), streams["stderr"].getvalue()
    assert ("\x1b" in out, "\x1b" in err) == (terminal == "stdout", terminal == "stderr")
    assert "configuration and read-only path checks passed" in out
    assert "configuration and read-only path checks failed" in err
    assert "fields: avatar.timezone" in err and "Not/AZone" not in err
    if terminal == "stderr":
        assert err.startswith(f"\n{BOLD}{RED}ERROR{RESET}  ")


def test_init_writes_a_minimal_template_that_loads_once_inputs_are_set(
    tmp_path: Path, sandbox: list[str], credentials: object, capsys: pytest.CaptureFixture
) -> None:
    target, before = tmp_path / "configs" / "new" / "avatar.yaml", files(tmp_path)
    assert main(["config", "init", str(target), "--avatar-id", "my-avatar"]) == 0
    guidance = capsys.readouterr().out
    assert "OPENAI_API_KEY" in guidance and "LIVEKIT_API_SECRET" in guidance
    # Starting validates the file; a manual check is offered as optional, not required.
    assert f"alphaavatar dev {target}" in guidance
    assert f"alphaavatar config check {target}" in guidance and "optional" in guidance
    # Only the requested file and its parents; no application or Avatar workspace.
    created = sorted(set(files(tmp_path)) - set(before))
    assert created == ["configs", "configs/new", "configs/new/avatar.yaml"]

    text = target.read_text()
    data = yaml.safe_load(text)
    assert data["avatar"]["id"] == "my-avatar"
    # No machine paths and no credential values: the Host still chooses platform paths.
    assert "application" not in data and str(tmp_path) not in text
    assert [name for name, secret in SECRETS.items() if secret in text] == []

    config = load_application(target)
    assert config.avatar.avatar.id == "my-avatar"
    DefaultMemoryConfig.model_validate(config.avatar.memory.init_config)
    DefaultPersonaConfig.model_validate(config.avatar.persona.init_config)
    assert main(["config", "check", str(target), "--json"]) == 0
    plugins = json.loads(capsys.readouterr().out)["plugins"]
    assert plugins["voice"] == {"vad": "silero", "stt": "openai_segment", "tts": "openai"}
    assert (plugins["memory"]["vdb"], plugins["persona"]["vdb"]) == ("lancedb", "lancedb")
    assert plugins["tools"] == {"deepresearch": None, "rag": None, "mcp": None}
    assert sandbox == []


def test_init_never_overwrites_and_leaves_nothing_behind_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    existing = tmp_path / "avatar.yaml"
    existing.write_text("keep: me\n")
    assert main(["config", "init", str(existing), "--avatar-id", "assistant"]) == 2
    assert "Refusing to overwrite" in capsys.readouterr().err
    assert existing.read_text() == "keep: me\n"

    # An invalid identifier fails before any directory or file exists.
    before = files(tmp_path)
    assert main(["config", "init", str(tmp_path / "a" / "b.yaml"), "--avatar-id", " x"]) == 2
    assert "fields: avatar.id" in capsys.readouterr().err
    assert files(tmp_path) == before

    real = Path.open

    class FullDisk(io.StringIO):
        def write(self, text: str) -> int:
            raise OSError(errno.ENOSPC, "No space left on device")

    def full(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if mode == "x":
            real(path, mode, *args, **kwargs).close()  # The file exists before the failure.
            return FullDisk()
        return real(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", full)
    before = files(tmp_path)
    assert main(["config", "init", str(tmp_path / "c" / "d" / "e.yaml"), "--avatar-id", "x"]) == 2
    assert "errno=28" in capsys.readouterr().err
    assert files(tmp_path) == before


def test_console_commands_run_without_the_host_log_socket(tmp_path: Path) -> None:
    entrypoint = Path(sys.executable).with_name("alphaavatar")
    target = tmp_path / "avatar.yaml"

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(entrypoint), *argv], capture_output=True, text=True, timeout=120, env=os.environ
        )

    assert run("config", "init", str(target), "--avatar-id", "console").returncode == 0
    checked = run("config", "check", str(target), "--json")
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["avatar_id"] == "console"
    assert files(tmp_path) == ["avatar.yaml", "home", "tmp"]
    # Only the converged commands exist; the removed entry points are usage errors.
    assert run("check", str(target)).returncode == 2
    assert run("config", "show", str(target)).returncode == 2
    commands = run("--help").stdout
    assert "{dev,start,config}" in commands  # No top-level check.
    assert "{init,check}" in run("config", "--help").stdout
