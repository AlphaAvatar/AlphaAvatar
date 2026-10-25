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
import multiprocessing as mp
import os
from collections.abc import Callable
from multiprocessing import resource_tracker
from pathlib import Path

import pytest
from inference_runner_samples import EchoRunner, FailingInitRunner, SlowInitRunner

from alphaavatar.agents.runtime.inference.process import RunnerProcess
from alphaavatar.agents.runtime.inference.runner import InferenceRunner

# Generous hang guards; the test asserts convergence, not CI wall-clock speed.
HANG_GUARD = 30


def runner(runner_cls: type[InferenceRunner]) -> RunnerProcess:
    return RunnerProcess(
        runner_cls,
        mp_ctx=mp.get_context("spawn"),
        initialize_timeout=HANG_GUARD,
        request_timeout=HANG_GUARD,
        close_timeout=0.5,
        max_pending=4,
    )


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.001)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


def open_descriptors() -> set[str] | None:
    """Return this process's descriptor targets, or None where /proc is unavailable."""
    directory = Path("/proc/self/fd")
    if not directory.is_dir():
        return None
    # The resource tracker is process-wide stdlib infrastructure, not runner-owned.
    resource_tracker.ensure_running()
    targets = set()
    for entry in directory.iterdir():
        try:
            targets.add(os.readlink(entry))
        except FileNotFoundError:
            pass  # The descriptor used to list the directory has already closed.
    return targets


def assert_released(process: RunnerProcess, pid: int | None, before: set[str] | None) -> None:
    assert pid is not None and process.pid is None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    after = open_descriptors()
    if before is not None and after is not None:
        assert after - before == set()


async def test_round_trip_errors_and_close_release_the_child() -> None:
    before = open_descriptors()
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
    before = open_descriptors()
    process = runner(FailingInitRunner)
    with pytest.raises(RuntimeError, match="RuntimeError") as failed:
        async with asyncio.timeout(HANG_GUARD):
            await process.start()
    assert "inference_runner_samples" in str(failed.value)
    assert "private model path" not in str(failed.value)
    assert process.pid is None
    after = open_descriptors()
    if before is not None and after is not None:
        assert after - before == set()


async def test_dispatched_timeout_retires_the_process_instead_of_reusing_it() -> None:
    before = open_descriptors()
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


async def test_cancelled_start_reaps_an_initializing_child() -> None:
    process = runner(SlowInitRunner)
    starting = asyncio.create_task(process.start())
    await asyncio.sleep(0.5)
    starting.cancel()
    # The child would initialize for 60 seconds; cancellation must converge well before that.
    async with asyncio.timeout(HANG_GUARD):
        with pytest.raises(asyncio.CancelledError):
            await starting
    assert process.pid is None
