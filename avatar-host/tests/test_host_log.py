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
"""Host log shutdown: a record queued before close is written before close returns."""

from __future__ import annotations

import io
import json
import logging
import os
import select
import threading
from pathlib import Path
from unittest import mock

import pytest

from alphaavatar.core.log.records import LOG_CLIENT_ENV
from alphaavatar.host.log.config import LogConfig
from alphaavatar.host.log.runtime import HostLog

HANG_GUARD = 30


def test_a_record_queued_after_an_empty_wait_is_written_before_close_returns(
    socket_root: Path, owned_addresses: set[object]
) -> None:
    real_select, stream = select.select, io.StringIO()
    armed, parked = threading.Event(), threading.Event()
    logs = HostLog(devmode=False, stream=stream)
    owned_addresses.add(json.loads(os.environ[LOG_CLIENT_ENV])["path"])

    def wait(*args: object) -> tuple[list, list, list]:
        result = real_select(*args)
        if armed.is_set() and not result[0] and threading.current_thread() is logs._thread:
            armed.clear()
            # This wait found nothing. Hand its result back only after close set the stop flag.
            parked.set()
            assert logs._stop.wait(HANG_GUARD)
        return result

    with mock.patch.object(select, "select", wait):
        armed.set()
        assert parked.wait(HANG_GUARD)
        logging.getLogger("alphaavatar.test").error("final diagnostic")
        # Queued before close, and unread: the writer is still holding its empty result.
        assert real_select((logs._socket,), (), (), 0)[0]
        logs.close()
    assert "final diagnostic" in stream.getvalue()
    assert list(socket_root.iterdir()) == []


def test_close_under_unending_input_fails_at_its_deadline_and_the_writer_still_exits(
    socket_root: Path, owned_addresses: set[object]
) -> None:
    real_select, flooding = select.select, threading.Event()
    logs = HostLog(devmode=False, stream=io.StringIO())
    owned_addresses.add(json.loads(os.environ[LOG_CLIENT_ENV])["path"])
    logs.activate(LogConfig(file=False, shutdown_timeout=0.1))

    def busy(*args: object) -> tuple[list, list, list]:
        if flooding.is_set() and threading.current_thread() is logs._thread:
            return [logs._socket], [], []  # Input never stops arriving.
        return real_select(*args)

    with mock.patch.object(select, "select", busy):
        flooding.set()
        # Records still arriving cannot be called drained: close reports it, bounded.
        with pytest.raises(RuntimeError, match="did not drain before its deadline"):
            logs.close()
        flooding.clear()
        assert logs._finished.wait(HANG_GUARD)
    assert list(socket_root.iterdir()) == []


def test_the_keys_a_configuration_names_never_reach_the_log_output(
    tmp_path: Path, socket_root: Path, owned_addresses: set[object]
) -> None:
    # Fictional values; only the first's name says it holds a secret. The bundle names the next
    # three, one through an interpolated api_key_env; a server's key is called after it: the
    # Host names them all for logs to hide. GITHUB_PAT is empty here, and the .env file's.
    from alphaavatar.agents.utils.env_utils import server_key
    from alphaavatar.core.log.events import log_event
    from alphaavatar.host.configs import load_application, select_configuration
    from alphaavatar.host.configs.credentials import load_environment
    from alphaavatar.host.configs.template import create_bundle
    from alphaavatar.host.workspace import ApplicationPaths

    values = {
        "OPENAI_API_KEY": "sk-openai-fictional-0042",
        "MODEL_AUTH": "auth-fictional-0042",
        "MCP_PAT": "pat-fictional-0042",
        "GITHUB_PAT": "gh-fictional-0042",
        server_key("https://gpu.invalid:8000/v1"): "sk-own-fictional-0042",
    }
    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True)
    # MCP servers as a profile writes them: a placeholder, and an interpolation that reads its
    # variable as the file loads, beside a header that reads an ordinary one, which stays shown.
    (paths.configs.profiles_dir / "alpha/plugins/tools/tools.yaml").write_text(
        "mcp:\n  plugin: default\n  enabled: true\n  servers:\n"
        "    docs:\n      url: https://mcp.invalid/\n"
        "      headers:\n        Authorization: Bearer <MCP_PAT>\n"
        "    code:\n      url: https://code.invalid/\n"
        "      headers:\n        Authorization: Bearer ${oc.env:GITHUB_PAT}\n"
        "        X-Region: ${oc.env:REGION}\n"
    )
    overrides = ["voice.tts.api_key_env=${oc.env:TTS_KEY_NAME,MODEL_AUTH}"]
    (tmp_path / "chosen.env").write_text(f"GITHUB_PAT={values['GITHUB_PAT']}\n")
    stream = io.StringIO()
    variables = values | {
        "GITHUB_PAT": "",
        "REGION": "region-west-0042",
        "ALPHAAVATAR_HOME": str(paths.root),
        "ENV_FILE": str(tmp_path / "chosen.env"),
    }
    with mock.patch.dict(os.environ, variables):
        os.environ.pop("TTS_KEY_NAME", None)
        settings = load_environment()
        load_application(select_configuration(None, overrides, settings), overrides, settings)
        logs = HostLog(devmode=True, stream=stream)
        owned_addresses.add(json.loads(os.environ[LOG_CLIENT_ENV])["path"])
        try:
            logs.refresh_secrets()
            logs.activate(LogConfig(file=False))
            logger = logging.getLogger("alphaavatar.test")
            held = " ".join(values.values())
            logger.error("request to https://gpu.invalid:8000/v1 with %s failed", held)
            logger.warning("MCP server https://code.invalid/ in region-west-0042 refused %s", held)
            try:
                raise RuntimeError(f"upstream refused {held}")
            except RuntimeError as error:  # Its text, as code that quotes it logs it.
                logger.exception("tool call failed: %s", str(error))
            log_event(logger, "model.started", model="gpt-test", reason=f"keys {held} sent")
        finally:
            logs.close()
    output = stream.getvalue()
    assert [name for name, value in values.items() if value in output] == []
    # What says what happened stays: the server, the failure, its type, the other field.
    for kept in (
        "https://gpu.invalid:8000/v1",
        "failed",
        "tool call failed: upstream refused",
        "https://code.invalid/ in region-west-0042 refused",
    ):
        assert kept in output
    assert "RuntimeError" in output and 'model="gpt-test"' in output
