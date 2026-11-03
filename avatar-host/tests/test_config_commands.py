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
"""config init / config check and selection: offline, side-effect free and credential safe."""

from __future__ import annotations

import errno
import io
import json
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import lancedb
import pytest
import qdrant_client
import yaml

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.configs import describe_application, load_application, select_configuration
from alphaavatar.host.configs.loader import restore_application
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
def color_capable() -> object:
    """Styling assertions must not depend on an inherited NO_COLOR or TERM=dumb."""
    with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}):
        os.environ.pop("NO_COLOR", None)
        yield


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
        f"    config     {config}",
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
        "    inference  7 runners, 1 worker each",
        "    health     127.0.0.1:8081 (dev: free port)",
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
    assert report["plugins"]["memory"] == {"plugin": "default", "vdb": "qdrant"}
    assert report["plugins"]["tools"]["mcp"] == {"plugin": "default", "servers": 1}
    assert report["health"] == {"bind": "127.0.0.1", "port": None}
    assert report["workspace"] == f"{report['home']}/avatars/renamed"

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
        text.splitlines()[3] == "    avatar_id  [redacted]" and summary["avatar_id"] == "[redacted]"
    )
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
    avatar = f"    {DIM}avatar_id{RESET}  assistant" if styled else "    avatar_id  assistant"
    assert checked.getvalue().splitlines()[3] == avatar
    assert ("\x1b" in checked.getvalue()) == styled
    # JSON never carries terminal styling, even on a terminal.
    assert "\x1b" not in as_json.getvalue() and json.loads(as_json.getvalue())["valid"]


@pytest.mark.parametrize("terminal", ["stdout", "stderr"])
def test_each_stream_detects_its_own_terminal(
    terminal: str, tmp_path: Path, color_capable: object
) -> None:
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


def test_credential_values_never_rewrite_fixed_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    # Header values equal to a fixed field name, and an empty bearer remainder.
    servers = {
        "docs": {"url": "https://mcp.invalid/a", "headers": {"Authorization": "Bearer health"}},
        "blank": {"url": "https://mcp.invalid/b", "headers": {"Authorization": "Bearer "}},
    }
    value = {"avatar": {"id": "assistant"}, "tools": {"mcp": {"enabled": True, "servers": servers}}}
    config = write(tmp_path / "avatar.json", value)

    assert main(["config", "check", str(config)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert main(["config", "check", str(config), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert lines[-2] == "    health     127.0.0.1:8081 (dev: free port)"
    assert lines[-4] == "    tools      deepresearch, rag, mcp (2 servers)"
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
    assert (report["avatar_id"], report["health"]["bind"]) == ("assistant", "127.0.0.1")
    view = describe_application(load_application(config))
    assert view["host"]["health"]["bind"] == "127.0.0.1"
    assert set(view["tools"]["mcp"]["servers"]) == {"docs", "blank"}


def test_runner_parallelism_is_checked_against_the_selected_plan_and_survives_restore(
    tmp_path: Path, sandbox: list[str], credentials: object, capsys: pytest.CaptureFixture
) -> None:
    config = write(tmp_path / "avatar.json", CONFIG)
    before = files(tmp_path)
    turn = "alphaavatar.router.turn_taking.smart_turn_v3"
    override = f"runtime.inference.methods={{{turn}: {{workers: 2}}}}"

    assert main(["config", "check", str(config), override]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert main(["config", "check", str(config), override, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert lines[-3] == f"    inference  7 runners  (workers: {turn} x2)"
    assert report["inference"][turn] == 2
    assert set(report["inference"].values()) == {1, 2}

    # The session child restores the same limits the Host builds its pool from.
    loaded = load_application(config, [override])
    restored = restore_application(loaded.payload)
    assert restored.avatar.runtime.inference == loaded.avatar.runtime.inference
    assert restored.avatar.runtime.inference.workers(turn) == 2

    # Rejected at load, located at the override: unselected, misspelled, or not replicable.
    for method, location in (
        ("alphaavatar.voice.vad.silero", "alphaavatar.voice.vad.silero"),
        (f"{turn}_v4", f"{turn}_v4"),
        ("alphaavatar.memory.vdb.qdrant", "alphaavatar.memory.vdb.qdrant.workers"),
    ):
        rejected = f"runtime.inference.methods={{{method}: {{workers: 2}}}}"
        assert main(["config", "check", str(config), rejected, "--json"]) == 2
        error = json.loads(capsys.readouterr().out)["error"]
        assert error["fields"] == [f"runtime.inference.methods.{location}"]
    assert main(["config", "check", str(config), "runtime.inference.max_pending=0"]) == 2
    assert "fields: runtime.inference.max_pending" in capsys.readouterr().err

    # Pure checks: no plan exported for workers, no process, client, socket or file.
    assert "ALPHAAVATAR_INFERENCE_PLAN" not in os.environ
    assert (sandbox, files(tmp_path)) == ([], before)


# The single-file template `config init` wrote before bundles, its YAML anchors included.
SINGLE_FILE_TEMPLATE = """\
avatar: {id: my-avatar, name: Assistant, introduction: You are a helpful voice AI assistant.}
defaults:
  embedding: &embedding {provider: openai, model: text-embedding-3-small}
  task: &task {provider: openai, model: gpt-4o, temperature: 0.1}
loop:
  plugin: realtime
  init_config: {model: {backend: openai, provider: openai, model: gpt-5.6-luna}}
voice:
  vad: {plugin: silero}
  stt: {plugin: openai_segment, model: gpt-4o-transcribe}
  tts: {plugin: openai, model: gpt-4o-mini-tts, speaker: ash}
vision: {enabled: false}
memory:
  vdb_config: {collection_name: memory, embedding: *embedding}
  init_config:
    conversation: {provider: {gateway: {tasks: {memory.conversation_delta: *task}}}}
    tool: {provider: {gateway: {tasks: {memory.tool_delta: *task}}}}
persona:
  vdb_config:
    profiler_collection_name: persona_profiler
    speaker_collection_name: persona_speaker
    face_collection_name: persona_face
    embedding: *embedding
  init_config:
    profiler: {provider: {gateway: {tasks: {persona.profile_delta: *task}}}}
tools: {deepresearch: {plugin: null}, rag: {plugin: null}, mcp: {enabled: false}}
"""
SECTIONS = ("loop", "voice", "vision", "memory", "persona", "tools")


@pytest.fixture
def home(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "application"
    with mock.patch.dict(os.environ, {"ALPHAAVATAR_HOME": str(root)}):
        yield root


def contents(root: Path) -> dict[str, bytes | None]:
    """Every path under root with its bytes; None marks a directory."""
    return {
        str(path.relative_to(root)): None if path.is_dir() else path.read_bytes()
        for path in root.rglob("*")
    }


def create(name: str, avatar_id: str) -> int:
    return main(["config", "init", name, "--avatar-id", avatar_id])


def profile(home: Path, name: str) -> Path:
    return home / "configs" / "profiles" / f"{name}.yaml"


def speaker(loaded: object) -> str:
    return json.loads(loaded.payload)["voice"]["tts"]["speaker"]


def test_init_splits_the_minimal_template_into_a_bundle_and_profiles_that_load_unchanged(
    tmp_path: Path,
    home: Path,
    sandbox: list[str],
    credentials: object,
    capsys: pytest.CaptureFixture,
) -> None:
    before = files(tmp_path)
    assert create("my-avatar", "my-avatar") == 0
    output = capsys.readouterr().out
    bundle = home / "configs" / "bundles" / "my-avatar.yaml"
    profiles = [profile(home, f"my-avatar/{section}") for section in SECTIONS]
    settings = home / "settings" / "settings.yaml"
    # Configuration files and their directories only: no cache, workspace or log.
    created = {
        str(path.relative_to(tmp_path))
        for target in (bundle, settings, *profiles)
        for path in (target, *target.parents)
        if path.is_relative_to(home)
    }
    assert sorted(set(files(tmp_path)) - set(before)) == sorted(created)
    # Locations and the default choice, never the configuration itself.
    assert f"  bundle    {bundle}\n" in output
    assert f"  profiles  {profiles[0].parent}  ({', '.join(SECTIONS)})\n" in output
    assert "  default   my-avatar (set as the default bundle)\n" in output
    assert "OPENAI_API_KEY" in output and "alphaavatar dev my-avatar" in output
    assert "gpt-4o" not in output and "silero" not in output

    for path in (bundle, *profiles):
        text = path.read_text()
        # Each file stands alone: no YAML anchor or alias reaches across files.
        events = list(yaml.parse(text))
        assert not any(isinstance(event, yaml.AliasEvent) for event in events)
        assert not any(getattr(event, "anchor", None) for event in events)
        assert str(tmp_path) not in text
        assert [name for name, secret in SECRETS.items() if secret in text] == []
    assert yaml.safe_load(bundle.read_text()) == {
        "avatar": {
            "id": "my-avatar",
            "name": "Assistant",
            "introduction": "You are a helpful voice AI assistant.",
        },
        "profiles": {section: f"my-avatar/{section}" for section in SECTIONS},
    }
    assert yaml.safe_load(settings.read_text()) == {"default_bundle": "my-avatar"}

    # The composed configuration is the previous single-file template, value for value.
    single = tmp_path / "single.yaml"
    single.write_text(SINGLE_FILE_TEMPLATE)
    expected = json.loads(load_application(single).payload)
    for target in (None, "my-avatar", str(bundle)):
        loaded = load_application(select_configuration(target))
        assert json.loads(loaded.payload) == expected
    DefaultMemoryConfig.model_validate(loaded.avatar.memory.init_config)
    DefaultPersonaConfig.model_validate(loaded.avatar.persona.init_config)
    assert main(["config", "check", "--json"]) == 0
    plugins = json.loads(capsys.readouterr().out)["plugins"]
    assert plugins["voice"] == {"vad": "silero", "stt": "openai_segment", "tts": "openai"}
    assert (plugins["memory"]["vdb"], plugins["persona"]["vdb"]) == ("lancedb", "lancedb")
    assert plugins["tools"] == {"deepresearch": None, "rag": None, "mcp": None}
    assert sandbox == []


def test_selection_follows_the_argument_spelling_from_any_directory(
    tmp_path: Path,
    home: Path,
    sandbox: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    assert create("alpha", "alpha") == 0 and create("beta", "beta-avatar") == 0
    capsys.readouterr()
    bundles = home / "configs" / "bundles"
    # Files in the working directory named like bundles are read only when spelled as files.
    for name in ("beta", "missing"):
        write(tmp_path / f"{name}.yaml", {"avatar": {"id": f"{name}-file"}})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    before = files(tmp_path)

    def checked(*argv: str) -> tuple[dict, str]:
        assert main(["config", "check", *argv, "--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        return report["config"], report["avatar_id"]

    def named(name: str, default: bool = False) -> dict:
        return {"bundle": name, "default": default, "file": str(bundles / f"{name}.yaml")}

    for directory in (tmp_path, elsewhere):
        monkeypatch.chdir(directory)
        assert checked() == (named("alpha", default=True), "alpha")
        assert checked("beta") == (named("beta"), "beta-avatar")
        # KEY=VALUE is always an override; alone, it overrides the default bundle.
        assert checked("avatar.id=renamed") == (named("alpha", default=True), "renamed")
        assert checked("beta", "avatar.id=renamed") == (named("beta"), "renamed")
        assert checked(str(bundles / "beta.yaml"))[1] == "beta-avatar"
    monkeypatch.chdir(tmp_path)
    local = {"bundle": None, "default": False, "file": str(tmp_path / "beta.yaml")}
    assert checked("beta.yaml") == checked("./beta.yaml") == (local, "beta-file")
    # A missing bundle never falls back to a file; a name outside the alphabet is no path.
    for argument, message in (
        ("missing", f"Bundle 'missing' does not exist: {bundles / 'missing.yaml'}"),
        ("Beta", "Bundle names use 1-64 lowercase letters"),
    ):
        assert main(["config", "check", argument]) == 2
        assert message in capsys.readouterr().err
    assert (files(tmp_path), sandbox) == (before, [])

    # Overrides apply to the composed configuration; profiles.<section> picks a reference.
    voice = profile(home, "beta/voice")
    voice.write_text(voice.read_text().replace("speaker: ash", "speaker: shimmer"))
    for overrides, expected in (
        ((), "ash"),
        (("voice.tts.speaker=nova",), "nova"),
        (("profiles.voice=beta/voice",), "shimmer"),
        (("profiles.voice=beta/voice", "voice.tts.speaker=nova"), "nova"),
    ):
        source = select_configuration("alpha", overrides)
        assert speaker(load_application(source, overrides)) == expected


def test_without_a_default_bundle_selection_fails_clearly_and_settings_never_choose_the_home(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    settings = home / "settings" / "settings.yaml"
    other = tmp_path / "other"
    for text in (None, "default_bundle: null\n", f"theme: dark\napplication: {{home: {other}}}\n"):
        if text is not None:
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(text)
        before = contents(tmp_path)
        assert main(["config", "check"]) == 2
        error = capsys.readouterr().err
        assert f"no default bundle in {settings};" in error
        assert "alphaavatar config init <name> --avatar-id <id>" in error
        assert contents(tmp_path) == before

    # The first bundle becomes the default beside the other settings; the home stays put.
    assert create("alpha", "alpha") == 0
    capsys.readouterr()
    assert yaml.safe_load(settings.read_text()) == {
        "theme": "dark",
        "application": {"home": str(other)},
        "default_bundle": "alpha",
    }
    assert main(["config", "check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["home"] == str(home)
    assert not other.exists()

    # A default naming a missing or malformed bundle fails without echoing the setting.
    for text, message in (
        ("default_bundle: gone\n", "Default bundle 'gone' does not exist"),
        (f"default_bundle: {SECRETS['vdb']}.Bad\n", f"default_bundle in {settings} is not"),
        ("- a list\n", "Settings must be a mapping"),
        (f"default_bundle: [{SECRETS['vdb']}\n", "Settings are not valid YAML"),
    ):
        settings.write_text(text)
        assert main(["config", "check"]) == 2
        error = capsys.readouterr().err
        assert message in error and SECRETS["vdb"] not in error


@pytest.mark.parametrize(
    ("bundle", "voice", "message"),
    [
        ({}, None, "profiles.voice references missing profile 'alpha/voice'"),
        ({"profiles": {"voice": "../alpha/voice"}}, "", "profiles.voice must be a profile name"),
        ({"profiles": {"voice": "/alpha/voice"}}, "", "profiles.voice must be a profile name"),
        ({"profiles": {"voice": "Alpha/Voice"}}, "", "profiles.voice must be a profile name"),
        ({"profiles": {"voice": "alpha/voice.yaml"}}, "", "profiles.voice must be a profile name"),
        ({"profiles": {"host": "alpha/voice"}}, "", "profiles may only fill character, context"),
        ({"profiles": "alpha/voice"}, "", "profiles must map plugin sections to profiles"),
        ({"voice": {"vad": {"plugin": "silero"}}}, "", "voice is set both inline and by profiles"),
        ({}, "profiles: {voice: alpha/voice}\n", "'alpha/voice' references profiles; only bundles"),
        ({}, "- vad\n", "profile 'alpha/voice' must be a mapping"),
        ({}, f"tts: {{speaker: '{SECRETS['vdb']}\n", "profile 'alpha/voice' is not valid YAML"),
        ({"application": {"home": "/elsewhere"}}, "", "sets another application.home"),
    ],
    ids=[
        "missing",
        "parent",
        "absolute",
        "uppercase",
        "suffix",
        "not-a-plugin",
        "not-a-mapping",
        "inline-and-profile",
        "self-reference",
        "profile-list",
        "profile-yaml",
        "bundle-home",
    ],
)
def test_reference_errors_locate_the_bundle_and_profile_without_values(
    bundle: dict, voice: str | None, message: str, tmp_path: Path, home: Path, capsys
) -> None:
    assert create("alpha", "alpha") == 0
    capsys.readouterr()
    path, target = home / "configs" / "bundles" / "alpha.yaml", profile(home, "alpha/voice")
    data = yaml.safe_load(path.read_text())
    for key, value in bundle.items():
        merge = isinstance(value, dict) and isinstance(data.get(key), dict)
        data[key] = data[key] | value if merge else value
    path.write_text(yaml.safe_dump(data))
    if voice is None:
        target.unlink()
    elif voice:
        target.write_text(voice)
    before = contents(tmp_path)

    assert main(["config", "check", "alpha"]) == 2
    error = capsys.readouterr().err
    assert main(["config", "check", "alpha", "--json"]) == 2
    report = json.loads(capsys.readouterr().out)["error"]
    assert "error: ConfigReferenceError\n    Bundle 'alpha'" in error and message in error
    assert report["type"] == "ConfigReferenceError" and message in report["diagnostic"]
    if voice is None:
        assert str(target) in error
    assert SECRETS["vdb"] not in error + json.dumps(report)
    assert contents(tmp_path) == before


def test_bundles_share_profiles_and_an_accepted_snapshot_stays_frozen(
    home: Path, capsys: pytest.CaptureFixture
) -> None:
    assert create("alpha", "alpha") == 0
    capsys.readouterr()
    # Generation groups profiles by bundle; any bundle may reference them.
    references = {"voice": "alpha/voice", "memory": "alpha/memory"}
    write(
        home / "configs" / "bundles" / "beta.yaml", {"avatar": {"id": "b"}, "profiles": references}
    )
    alpha, beta = (load_application(select_configuration(name)) for name in ("alpha", "beta"))
    for section in references:
        assert json.loads(beta.payload)[section] == json.loads(alpha.payload)[section]

    voice = profile(home, "alpha/voice")
    voice.write_text(voice.read_text().replace("speaker: ash", "speaker: nova"))
    assert speaker(load_application(select_configuration("beta"))) == "nova"
    # Sessions restore the accepted payload; profiles on disk are never read again.
    shutil.rmtree(home / "configs" / "profiles")
    for accepted in (alpha, beta):
        restored = restore_application(accepted.payload)
        assert json.loads(restored.payload) == json.loads(accepted.payload)
        assert speaker(restored) == "ash"


def test_checking_a_bundle_reads_only_and_hides_profile_credentials(
    tmp_path: Path,
    home: Path,
    sandbox: list[str],
    credentials: object,
    capsys: pytest.CaptureFixture,
) -> None:
    assert create("alpha", "alpha") == 0
    capsys.readouterr()
    for section, change in (("memory", CONFIG["memory"]), ("tools", CONFIG["tools"])):
        path = profile(home, f"alpha/{section}")
        data = yaml.safe_load(path.read_text())
        for key, value in change.items():
            data[key] = data.get(key, {}) | value
        path.write_text(yaml.safe_dump(data))
    before, environment = contents(tmp_path), dict(os.environ)

    for argv in (["alpha"], ["alpha", "--json"], [], ["--json"]):
        assert main(["config", "check", *argv]) == 0
        output = capsys.readouterr().out
        assert [name for name, secret in SECRETS.items() if secret in output] == []
    # Nothing created (no cache or workspace), no variable written, no client constructed.
    assert (contents(tmp_path), dict(os.environ), sandbox) == (before, environment, [])
    payload = json.loads(load_application(select_configuration("alpha")).payload)
    assert payload["memory"]["vdb_config"]["api_key"] == SECRETS["vdb"]
    headers = payload["tools"]["mcp"]["servers"]["docs"]["headers"]
    assert headers == {"Authorization": f"Bearer {SECRETS['MCP_DOCS_TOKEN']}"}


def test_init_never_overwrites_reuses_directories_and_keeps_an_existing_default(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    settings = home / "settings" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text("# Personal settings.\ntheme: dark\n")
    notes = home / "configs" / "profiles" / "alpha" / "notes.txt"
    notes.parent.mkdir(parents=True)
    notes.write_text("keep")
    assert create("alpha", "alpha") == 0
    assert "alpha (set as the default bundle)" in capsys.readouterr().out
    # Appending keeps the other settings and their comments exactly.
    kept = "# Personal settings.\ntheme: dark\ndefault_bundle: alpha\n"
    assert (settings.read_text(), notes.read_text()) == (kept, "keep")

    # An existing bundle, or any profile it would write, refuses before anything changes.
    taken = profile(home, "beta/voice")
    taken.parent.mkdir()
    taken.write_text("keep: me\n")
    before = contents(tmp_path)
    for name, existing in (("alpha", home / "configs" / "bundles" / "alpha.yaml"), ("beta", taken)):
        assert create(name, "other") == 2
        assert f"Refusing to overwrite an existing file: {existing}" in capsys.readouterr().err
        assert contents(tmp_path) == before

    # Another bundle keeps the default and every settings byte; a non-ASCII ID survives.
    assert create("gamma", "助手-1") == 0
    assert "alpha (unchanged)" in capsys.readouterr().out
    assert settings.read_text() == kept
    assert load_application(select_configuration("gamma")).avatar.avatar.id == "助手-1"

    # Invalid names, IDs or settings fail before any file or directory exists.
    before = contents(tmp_path)
    for name, identity, message in (
        ("my-avatar.yaml", "x", "Bundle names use"),
        ("Delta", "x", "Bundle names use"),
        ("../delta", "x", "Bundle names use"),
        ("delta", " x", "fields: avatar.id"),
        # A line break YAML would fold into a space.
        ("delta", "a\x85b", "fields: avatar.id"),
    ):
        assert create(name, identity) == 2
        assert message in capsys.readouterr().err
        assert contents(tmp_path) == before
    settings.write_text("- not a mapping\n")
    before = contents(tmp_path)
    assert create("delta", "delta") == 2
    assert "Settings must be a mapping" in capsys.readouterr().err
    assert contents(tmp_path) == before


@pytest.mark.parametrize(
    ("failure", "code"),
    [("profile-write", 28), ("profile-directory", 13), ("settings-replace", 5), ("new-home", 5)],
)
def test_a_failed_init_removes_only_what_it_created(
    failure: str, code: int, tmp_path: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    if failure != "new-home":
        # Content to keep: another bundle with its profiles, and settings without a default.
        assert create("other", "other") == 0
        (home / "settings" / "settings.yaml").write_text("# Mine.\ntheme: dark\n")
    capsys.readouterr()
    before = contents(tmp_path)
    real_open, real_mkdir, opened = Path.open, os.mkdir, []

    class FullDisk(io.StringIO):
        def write(self, text: str) -> int:
            raise OSError(errno.ENOSPC, "No space left on device")

    def full(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if mode == "x":
            opened.append(path)
            if len(opened) == 3:
                # The bundle and one profile exist; this file exists before writing fails.
                real_open(path, mode, *args, **kwargs).close()
                return FullDisk()
        return real_open(path, mode, *args, **kwargs)

    def denied(path: object, *args: object, **kwargs: object) -> None:
        if Path(path) == home / "configs" / "profiles" / "new":
            raise OSError(errno.EACCES, "Permission denied")
        real_mkdir(path, *args, **kwargs)

    def unreplaceable(*args: object) -> None:
        raise OSError(errno.EIO, "Input/output error")

    patch = {
        "profile-write": mock.patch.object(Path, "open", full),
        "profile-directory": mock.patch.object(os, "mkdir", denied),
    }.get(failure, mock.patch.object(os, "replace", unreplaceable))
    with patch:
        assert create("new", "new") == 2
    assert f"errno={code}" in capsys.readouterr().err
    assert contents(tmp_path) == before


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
    configuration = sorted(
        str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()
    )
    assert configuration == sorted(
        [
            "configs/bundles/console.yaml",
            *(f"configs/profiles/console/{section}.yaml" for section in SECTIONS),
            "settings/settings.yaml",
        ]
    )
    # start and dev select alike: a missing bundle fails before anything is created.
    started = run("start", "absent")
    assert started.returncode == 2
    assert "Bundle 'absent' does not exist" in started.stdout + started.stderr
    assert sorted(path.name for path in home.iterdir()) == ["configs", "settings"]
    # Only the converged commands exist; the removed entry points are usage errors.
    assert run("check", "console").returncode == 2
    assert run("config", "show", "console").returncode == 2
    commands = run("--help").stdout
    assert "{dev,start,config}" in commands  # No top-level check.
    assert "{init,check}" in run("config", "--help").stdout
