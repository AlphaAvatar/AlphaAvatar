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
"""Spawned RunnerProcess ownership, using socketpair IPC and no shared runtime endpoint."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import multiprocessing as mp
import os
from collections import Counter
from pathlib import Path

import pytest
from inference_checks import HANG_GUARD, descriptors, settled, wait_until
from inference_runner_samples import ClosingRunner, EchoRunner, FailingInitRunner

from alphaavatar.agents.runtime.inference.process import RunnerProcess
from alphaavatar.agents.runtime.inference.runner import InferenceRunner, RunnerLaunch

# Generous hang guards; the test asserts convergence, not CI wall-clock speed.


def runner(
    runner_cls: type[InferenceRunner], *, root: Path | None = None, close_timeout: float = 0.5
) -> RunnerProcess:
    launch = None
    if root is not None:
        config = json.dumps({"test": {"root": str(root)}})
        launch = RunnerLaunch(str(root), str(root / "models"), config=config)
    return RunnerProcess(
        runner_cls,
        mp_ctx=mp.get_context("spawn"),
        initialize_timeout=HANG_GUARD,
        request_timeout=HANG_GUARD,
        close_timeout=close_timeout,
        max_pending=4,
        launch=launch,
    )


def assert_released(process: RunnerProcess, pid: int | None, before: Counter[str] | None) -> None:
    assert pid is not None and process.pid is None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    after = descriptors()
    if before is not None and after is not None:
        assert after - before == Counter()


async def test_round_trip_errors_and_close_release_the_child() -> None:
    before = descriptors()
    process = runner(EchoRunner)
    async with asyncio.timeout(HANG_GUARD):
        await process.start()
    pid = process.pid
    assert await process.run(b"frame") == b"frame"
    assert await process.run(b"none") is None
    with pytest.raises(RuntimeError, match="ValueError") as failed:
        await process.run(b"fail")
    # Runner diagnostics carry type and frames, never exception messages.
    assert "private request detail" not in str(failed.value)
    assert await process.run(b"after-error") == b"after-error"
    async with asyncio.timeout(HANG_GUARD):
        await process.close()
    assert_released(process, pid, before)


async def test_initialization_error_is_reported_and_reaped() -> None:
    before = descriptors()
    process = runner(FailingInitRunner)
    with pytest.raises(RuntimeError, match="RuntimeError") as failed:
        async with asyncio.timeout(HANG_GUARD):
            await process.start()
    assert "inference_runner_samples" in str(failed.value)
    assert "private model path" not in str(failed.value)
    assert process.pid is None
    after = descriptors()
    if before is not None and after is not None:
        assert after - before == Counter()


async def test_dispatched_timeout_retires_the_process_instead_of_reusing_it() -> None:
    before = descriptors()
    process = runner(EchoRunner)
    async with asyncio.timeout(HANG_GUARD):
        await process.start()
    pid = process.pid
    with pytest.raises(TimeoutError):
        await process.run(b"sleep:60", timeout=0.2)
    assert not process.is_alive
    with pytest.raises(RuntimeError, match="unavailable"):
        await process.run(b"frame")
    async with asyncio.timeout(HANG_GUARD):
        await process.close()
    assert_released(process, pid, before)


async def test_cancelled_queued_request_is_withdrawn_without_breaking_the_runner() -> None:
    process = runner(EchoRunner)
    async with asyncio.timeout(HANG_GUARD):
        await process.start()
    # Read-only inspection of the existing exchange registry; no production interface is added.
    exchanges = process._requests

    def dispatch_states() -> list[bool]:
        return [request.dispatched for request in exchanges.values()]

    def queued_behind_lock() -> bool:
        tasks = list(exchanges)
        # Acquiring the serial lock is the only suspension point before dispatch.
        return (
            dispatch_states() == [True, False]
            and inspect.getcoroutinestate(tasks[1].get_coro()) == inspect.CORO_SUSPENDED
        )

    dispatched = asyncio.create_task(process.run(b"sleep:1"))
    await wait_until(
        lambda: process._lock.locked() and dispatch_states() == [True],
        "the first request never occupied the runner",
    )
    queued = asyncio.create_task(process.run(b"queued"))
    await wait_until(queued_behind_lock, "the second request never waited behind the first")
    first_exchange, queued_exchange = exchanges
    assert process._lock.locked() and not dispatched.done()

    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    await wait_until(
        lambda: list(exchanges) == [first_exchange], "the queued exchange was not withdrawn"
    )
    assert queued_exchange.cancelled()
    assert await dispatched == b"sleep:1"
    assert process.is_alive
    # A withdrawn request that reached the runner would desynchronize this response.
    assert await process.run(b"next") == b"next"
    async with asyncio.timeout(HANG_GUARD):
        await process.close()


async def test_ready_runner_still_closes_through_its_drain_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=RunnerProcess.__module__)
    process = runner(ClosingRunner, root=tmp_path, close_timeout=2 * HANG_GUARD)
    async with asyncio.timeout(HANG_GUARD):
        await process.start()
        assert await process.run(b"frame") == b"frame"
        await process.close()
    assert process.pid is None
    assert (tmp_path / f"{ClosingRunner.INFERENCE_METHOD}.closed").exists()
    assert settled(caplog, ClosingRunner.INFERENCE_METHOD) == (0, False)
