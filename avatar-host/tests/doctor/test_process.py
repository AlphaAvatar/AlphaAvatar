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
"""The diagnostic process's supervisor: a process whose exit is noticed is reaped, not killed,
however long the kernel takes to make it reapable; one that never exits is killed at its
deadline, said as it was; cancelled, it still closes; what it leaves in its group goes."""

from __future__ import annotations

import asyncio
import multiprocessing.process
import os
import time
from pathlib import Path

import doctor_doubles as doubles
import pytest

from alphaavatar.host.tools.doctor import process as doctor_process


def supervise(run: Path, *, limit: float = 30.0) -> tuple[object, list[str], float]:
    """The supervisor over a diagnostic process of the test's own: its report, what
    reclaiming found, and how long it took."""
    problems: list[str] = []
    args = ("", None, (), (), str(run), None, 1, None)
    began = time.monotonic()

    async def run_it() -> object:
        return await doctor_process._supervise(args, limit, asyncio.Event(), problems)

    found = asyncio.run(run_it())
    return found, problems, time.monotonic() - began


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def reaped_late(monkeypatch: pytest.MonkeyPatch, seconds: float) -> list[str]:
    """The window the kernel leaves between closing a process's pipes, which tells it has
    exited, and its being reapable: ``is_alive`` true for ``seconds`` once first asked. The
    kills there would be, recorded."""
    real = multiprocessing.process.BaseProcess.is_alive
    first: list[float] = []
    killed: list[str] = []

    def is_alive(self: multiprocessing.process.BaseProcess) -> bool:
        first or first.append(time.monotonic())
        return time.monotonic() - first[0] < seconds or real(self)

    kill = doctor_process._kill
    monkeypatch.setattr(multiprocessing.process.BaseProcess, "is_alive", is_alive)
    monkeypatch.setattr(
        doctor_process, "_kill", lambda group, owner: (killed.append("kill"), kill(group, owner))
    )
    return killed


def test_a_process_whose_exit_is_noticed_before_it_can_be_reaped_is_reaped_not_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed = reaped_late(monkeypatch, 0.05)
    monkeypatch.setattr(doctor_process, "_main", doubles.reports)
    found, problems, _ = supervise(tmp_path)
    assert (found, problems, killed) == (({}, ""), [], [])


def test_a_process_that_returns_is_reaped_with_nothing_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor_process, "_main", doubles.reports)
    found, problems, _ = supervise(tmp_path)
    assert (found, problems) == (({}, ""), [])


def test_a_process_that_never_becomes_reapable_is_killed_at_its_reap_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed = reaped_late(monkeypatch, 0.6)
    monkeypatch.setattr(doctor_process, "REAP_SECONDS", 0.2)
    monkeypatch.setattr(doctor_process, "_main", doubles.reports)
    _, problems, _ = supervise(tmp_path)
    assert killed == ["kill"]
    assert problems == [
        "the diagnostic process closed its pipes but was not reaped within 0.2 s: killed"
    ]


def test_a_process_that_does_not_stop_is_killed_at_its_close_deadline_said_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor_process, "CLOSE_SECONDS", 1.0)
    monkeypatch.setattr(doctor_process, "_main", doubles.deaf)
    found, problems, took = supervise(tmp_path, limit=0.5)
    assert 1.5 <= took < 10
    assert found == (None, "the diagnostic process exited with code -9")
    assert problems == [
        "the diagnostic process had not exited 1.0 s after it was asked to stop, its 1 s to "
        "close: killed"
    ]
    assert gone(int((tmp_path / "started").read_text()))


@pytest.mark.parametrize("child", ["stops", "deaf"])
def test_a_cancelled_supervisor_still_closes_the_process_by_its_deadlines(
    child: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelled, it asks the process to stop: one that stops is reaped, not killed; one
    that does not is killed when its time to close is up. Either way the cancellation goes
    on to the caller."""
    monkeypatch.setattr(doctor_process, "CLOSE_SECONDS", 1.0)
    monkeypatch.setattr(doctor_process, "_main", getattr(doubles, child))
    problems: list[str] = []
    args = ("", None, (), (), str(tmp_path), None, 1, None)

    async def cancelled() -> None:
        task = asyncio.ensure_future(
            doctor_process._supervise(args, 30.0, asyncio.Event(), problems)
        )
        while not (tmp_path / "started").exists():
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancelled())
    pid = int((tmp_path / "started").read_text())
    assert gone(pid)
    if child == "stops":
        assert problems == [] and (tmp_path / "report.pickle").exists()
    else:
        assert problems == [
            "the diagnostic process had not exited 1.0 s after it was asked to stop, its 1 s "
            "to close: killed"
        ]


def test_what_the_process_leaves_running_in_its_group_is_killed_and_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor_process, "_main", doubles.leaves)
    found, problems, _ = supervise(tmp_path)
    assert found == ({}, "")
    assert problems == ["processes the diagnostic process started were still running: killed"]
    left = int((tmp_path / "left").read_text())
    for _ in range(100):
        if gone(left):
            break
        time.sleep(0.05)
    assert gone(left)
