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
"""Safe configuration views and the checked inference plan, offline and credential safe."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from config_samples import CONFIG, SECRETS, files, write

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.configs import describe_application, load_application
from alphaavatar.host.configs.loader import restore_application


def test_safe_projection_keeps_useful_settings_without_credentials(
    tmp_path: Path, sandbox: list[str], credentials: object
) -> None:
    # Over the 8192-character log bound; plugin mappings may carry hostile keys too.
    introduction = "Keep [bold red]this[/] and [hidden] literal: " + "word " * 1800 + "end"
    # Credentials equal to a fixed field name, or empty after their scheme, rewrite no field.
    servers = CONFIG["tools"]["mcp"]["servers"] | {
        "plain": {"url": "https://mcp.invalid/a", "headers": {"Authorization": "Bearer health"}},
        "blank": {"url": "https://mcp.invalid/b", "headers": {"Authorization": "Bearer "}},
    }
    value = CONFIG | {
        "avatar": {"id": "assistant", "introduction": f"{introduction} {SECRETS['vdb']}\x1b[31m"},
        "context": {"init_config": {"key\x1b[2J": 1}},
        "tools": {"mcp": {"enabled": True, "servers": servers}},
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
    assert set(view["tools"]["mcp"]["servers"]) == {"docs", "plain", "blank"}
    assert view["host"]["health"]["bind"] == "127.0.0.1"
    # Complete text, a reused credential replaced and terminal escapes removed, keys included.
    assert view["avatar"]["introduction"] == f"{introduction} [redacted]"
    assert view["context"]["init_config"] == {"key": 1}
    assert [name for name, secret in SECRETS.items() if secret in text] == []
    assert "\\u001b" not in text and yaml.safe_load(yaml.safe_dump(view)) == view
    assert sandbox == []


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
    runners = len(report["inference"])
    assert f"      inference     {runners} runners  (workers: {turn} x2)" in lines
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
