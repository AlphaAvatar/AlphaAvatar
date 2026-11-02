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
"""check, config show and config init: offline, side-effect free and credential safe."""

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
from alphaavatar.host.configs.loader import load_application
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


def test_check_reports_valid_and_invalid_configurations_with_effective_overrides(
    tmp_path: Path, sandbox: list[str], credentials: object, capsys: pytest.CaptureFixture
) -> None:
    config = write(tmp_path / "avatar.json", CONFIG)
    before = files(tmp_path)

    assert main(["check", str(config), "avatar.id=renamed", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    # The override is the configuration that would start, including its default workspace.
    assert report["valid"] and report["avatar_id"] == "renamed"
    assert report["workspace"] == f"{report['home']}/avatars/renamed"

    assert main(["check", str(config), "tools.mcp.token=leak"]) == 2
    output = capsys.readouterr()
    assert "fields: tools.mcp.token" in output.err and "leak" not in output.out + output.err
    assert main(["check", str(config), "avatar.timezone=Not/AZone", "--json"]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["valid"] is False
    assert failure["error"]["fields"] == ["avatar.timezone"]
    assert "Not/AZone" not in json.dumps(failure)

    # No Host, client, socket, child process or workspace: only the input file exists.
    assert (sandbox, files(tmp_path)) == ([], before)


def test_show_prints_the_effective_configuration_without_credentials(
    tmp_path: Path, sandbox: list[str], credentials: object, capsys: pytest.CaptureFixture
) -> None:
    config = write(tmp_path / "avatar.json", CONFIG)
    before = files(tmp_path)
    overrides = ["voice.tts.speed=1.3", "loop.plugin=realtime"]

    assert main(["config", "show", str(config), *overrides, "--json"]) == 0
    view = json.loads(capsys.readouterr().out)
    assert main(["config", "show", str(config), *overrides]) == 0
    text = capsys.readouterr().out

    assert yaml.safe_load(text) == view
    # Useful, non-sensitive facts stay: selections, parameters, overrides and resolved paths.
    assert (view["voice"]["tts"]["speed"], view["loop"]["plugin"]) == (1.3, "realtime")
    assert view["avatar"]["workspace_root"] == f"{view['application']['home']}/avatars/assistant"
    assert view["memory"]["vdb_config"] == {"url": "[hidden]", "api_key": "[hidden]"}
    assert view["tools"]["mcp"]["servers"]["docs"]["headers"] == {"Authorization": "[hidden]"}
    assert view["avatar"]["introduction"] == "Uses [redacted] inline."
    for output in (text, json.dumps(view)):
        assert [name for name, secret in SECRETS.items() if secret in output] == []
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
    for command in (["check"], ["config", "show"]):
        assert main([*command, str(config), *(["--json"] if as_json else [])]) == 2
        output = capsys.readouterr()
        streams = output.out + output.err
        assert SECRETS["vdb"] not in streams
        if as_json:
            error = json.loads(output.out)["error"]
            assert error["type"] == "ValidationError" and error["fields"]
            assert set(error) == {"type", "fields", "diagnostic"}
        else:
            assert "fields: " in output.err
    assert sandbox == []


def test_init_writes_a_minimal_template_that_loads_once_inputs_are_set(
    tmp_path: Path, sandbox: list[str], credentials: object, capsys: pytest.CaptureFixture
) -> None:
    target, before = tmp_path / "configs" / "new" / "avatar.yaml", files(tmp_path)
    assert main(["config", "init", str(target), "--avatar-id", "my-avatar"]) == 0
    guidance = capsys.readouterr().out
    assert "OPENAI_API_KEY" in guidance and "LIVEKIT_API_SECRET" in guidance
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
    assert main(["check", str(target)]) == 0
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
    checked = run("check", str(target), "--json")
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["avatar_id"] == "console"
    shown = run("config", "show", str(target), "--json")
    assert json.loads(shown.stdout)["avatar"]["id"] == "console"
    assert files(tmp_path) == ["avatar.yaml", "home", "tmp"]
    help_text = run("--help").stdout
    assert all(command in help_text for command in ("dev", "start", "check", "config"))
