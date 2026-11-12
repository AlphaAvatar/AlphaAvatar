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
