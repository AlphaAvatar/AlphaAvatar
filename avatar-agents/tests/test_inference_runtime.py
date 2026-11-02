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
"""Shared InferenceRuntime ownership over real spawned runners and the owned local endpoint."""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
import signal
from collections import Counter
from collections.abc import Callable
from multiprocessing import resource_tracker
from pathlib import Path

import pytest
from inference_runner_samples import (
    EchoRunner,
    FailingCloseRunner,
    FailingInitRunner,
    JournalRunner,
    SecondJournalRunner,
    SlowInitRunner,
)

from alphaavatar.agents.runtime.inference import (
    INFERENCE_ENDPOINT_ENV,
    InferenceExecutor,
    InferenceRunner,
    InferenceRuntime,
    RunnerLaunch,
)

HANG_GUARD = 30
ECHO, JOURNAL = EchoRunner.INFERENCE_METHOD, JournalRunner.INFERENCE_METHOD
SECOND = SecondJournalRunner.INFERENCE_METHOD


def service(
    root: Path, *runners: type[InferenceRunner], close_timeout: float = 1, **options: int
) -> InferenceRuntime:
    launch = RunnerLaunch(
        str(root), str(root / "models"), config=json.dumps({"test": {"root": str(root)}})
    )
    return InferenceRuntime(
        {runner.INFERENCE_METHOD: runner for runner in runners},
        mp_ctx=mp.get_context("spawn"),
        launch=launch,
        initialize_timeout=HANG_GUARD,
        request_timeout=HANG_GUARD,
        close_timeout=close_timeout,
        **options,
    )


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.002)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


def journal(root: Path, method: str = JOURNAL) -> list[tuple[int, str]]:
    path = root / f"{method}.journal"
    lines = path.read_text().splitlines() if path.exists() else []
    return [(int(pid), data) for pid, data in (line.split(" ", 1) for line in lines)]


def dispatch_states(runtime: InferenceRuntime, method: str) -> list[bool]:
    # Read-only view of the existing exchange registry; no production interface is added.
    return [request.dispatched for request in runtime._runners[method]._requests.values()]


def children() -> set[int]:
    return {process.pid for process in mp.active_children()}


def descriptors() -> Counter[str] | None:
    directory = Path("/proc/self/fd")
    if not directory.is_dir():
        return None
    resource_tracker.ensure_running()  # Process-wide stdlib facility, not runner-owned.
    # Count per target: two leaked descriptors may share one target such as a pipe.
    targets: Counter[str] = Counter()
    for entry in directory.iterdir():
        try:
            targets[os.readlink(entry)] += 1
        except FileNotFoundError:
            pass
    return targets


def assert_released(socket_root: Path, before: set[int], fds: Counter[str] | None) -> None:
    assert children() - before == set()
    assert INFERENCE_ENDPOINT_ENV not in os.environ
    assert list(socket_root.iterdir()) == []
    after = descriptors()
    if fds is not None and after is not None:
        assert after - fds == Counter()


async def test_methods_progress_independently_while_each_method_stays_serial(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    runtime = service(tmp_path, JournalRunner, EchoRunner)
    first = second = None
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        first, second = InferenceExecutor(runtime.endpoint), InferenceExecutor(runtime.endpoint)

        blocked = asyncio.create_task(first.do_inference(JOURNAL, b"gate:a"))
        await wait_until(lambda: (tmp_path / "a.entered").exists(), "the gate was never entered")
        queued = asyncio.create_task(second.do_inference(JOURNAL, b"queued"))
        await wait_until(
            lambda: dispatch_states(runtime, JOURNAL) == [True, False],
            "the second session never queued behind the occupied method",
        )
        # Another method, from either session, is not delayed by the occupied runner.
        assert await first.do_inference(ECHO, b"first-echo") == b"first-echo"
        assert await second.do_inference(ECHO, b"second-echo") == b"second-echo"
        assert [data for _, data in journal(tmp_path)] == ["gate:a"]
        assert not blocked.done() and not queued.done()

        (tmp_path / "a.open").touch()
        assert await blocked == b"gate:a"
        assert await queued == b"queued"
        records = journal(tmp_path)
        assert [data for _, data in records] == ["gate:a", "queued"]
        assert len({pid for pid, _ in records}) == 1
    finally:
        for executor in (first, second):
            if executor is not None:
                await executor.close()
        await runtime.close()


async def test_capacity_limits_reject_excess_work_without_disturbing_admitted_requests(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    runtime = service(tmp_path, JournalRunner, EchoRunner, max_pending_per_runner=2)
    executors: list[InferenceExecutor] = []
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        limited = InferenceExecutor(runtime.endpoint, max_connections=1, max_pending_per_method=1)
        queued_session, rejected_session = (InferenceExecutor(runtime.endpoint) for _ in range(2))
        executors.extend((limited, queued_session, rejected_session))

        blocked = asyncio.create_task(limited.do_inference(JOURNAL, b"gate:b"))
        await wait_until(lambda: (tmp_path / "b.entered").exists(), "the gate was never entered")
        # Client limits fail locally: one pending call per method, one method per executor here.
        with pytest.raises(RuntimeError, match="at capacity"):
            await limited.do_inference(JOURNAL, b"client-overflow")
        with pytest.raises(RuntimeError, match="connection capacity exhausted"):
            await limited.do_inference(ECHO, b"client-method-overflow")

        queued = asyncio.create_task(queued_session.do_inference(JOURNAL, b"queued"))
        await wait_until(
            lambda: dispatch_states(runtime, JOURNAL) == [True, False], "no request queued"
        )
        # The runner's bounded queue rejects a third session instead of waiting unbounded.
        with pytest.raises(RuntimeError, match="at capacity"):
            await rejected_session.do_inference(JOURNAL, b"service-overflow")

        (tmp_path / "b.open").touch()
        assert await blocked == b"gate:b"
        assert await queued == b"queued"
        assert await rejected_session.do_inference(JOURNAL, b"after") == b"after"
        assert [data for _, data in journal(tmp_path)] == ["gate:b", "queued", "after"]
    finally:
        for executor in executors:
            await executor.close()
        await runtime.close()


async def test_failed_runner_recovers_in_a_new_process_without_replaying_attempted_work(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    before = children()
    runtime = service(tmp_path, JournalRunner, EchoRunner, restart_limit=2)
    executor = None
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executor = InferenceExecutor(runtime.endpoint)
        first_pid = int(await executor.do_inference(JOURNAL, b"pid"))
        assert await executor.do_inference(ECHO, b"connected") == b"connected"

        # A timeout after dispatch retires the process; its outcome is never guessed or replayed.
        attempt = asyncio.create_task(runtime.do_inference(JOURNAL, b"gate:t", timeout=1.0))
        await wait_until(
            lambda: (tmp_path / "t.entered").exists() or attempt.done(), "never dispatched"
        )
        with pytest.raises(TimeoutError):
            await attempt
        assert not runtime.is_alive
        assert {view.method: view.ready for view in runtime.snapshot()} == {
            JOURNAL: False,
            ECHO: True,
        }
        # An established session connection to a healthy method keeps progressing.
        assert await executor.do_inference(ECHO, b"independent") == b"independent"
        with pytest.raises(RuntimeError, match="temporarily unavailable"):
            await executor.do_inference(JOURNAL, b"while-failed")

        async with asyncio.timeout(HANG_GUARD):
            assert await runtime.recover_failed_runners()
        second_pid = int(await executor.do_inference(JOURNAL, b"pid"))
        assert second_pid != first_pid

        # A runner lost mid-request reports failure to its caller; the request is not resent.
        lost = asyncio.create_task(executor.do_inference(JOURNAL, b"gate:k"))
        await wait_until(lambda: (tmp_path / "k.entered").exists(), "the gate was never entered")
        os.kill(second_pid, signal.SIGKILL)
        with pytest.raises(RuntimeError):
            await lost
        async with asyncio.timeout(HANG_GUARD):
            assert await runtime.recover_failed_runners()
        third_pid = int(await executor.do_inference(JOURNAL, b"pid"))
        assert third_pid not in (first_pid, second_pid)

        # The bounded restart budget is exhausted; the failure stays visible to the owner.
        os.kill(third_pid, signal.SIGKILL)
        await wait_until(lambda: not runtime.is_alive, "the killed runner was never observed")
        async with asyncio.timeout(HANG_GUARD):
            assert not await runtime.recover_failed_runners()
        assert not runtime.is_alive
        assert await executor.do_inference(ECHO, b"still-independent") == b"still-independent"

        records = journal(tmp_path)
        assert {pid for pid, data in records if data == "gate:t"} <= {first_pid}
        assert [pid for pid, data in records if data == "gate:k"] == [second_pid]
        assert [data for pid, data in records if pid == third_pid] == ["pid"]
        assert "while-failed" not in {data for _, data in records}
    finally:
        if executor is not None:
            await executor.close()
        await runtime.close()
    assert children() - before == set()


async def test_failed_method_does_not_refuse_first_use_of_a_healthy_method(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    runtime = service(tmp_path, JournalRunner, SecondJournalRunner)
    executor = None
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executor = InferenceExecutor(runtime.endpoint)
        os.kill(int(await executor.do_inference(JOURNAL, b"pid")), signal.SIGKILL)
        await wait_until(lambda: not runtime.is_alive, "the killed runner was never observed")

        # A session's first request to another, healthy method opens a new connection.
        assert await executor.do_inference(SECOND, b"first-use") == b"first-use"
        assert await runtime.do_inference(SECOND, b"in-process") == b"in-process"
        # A cancelled caller drops its channel; reconnecting during the failure is admitted too.
        caller = asyncio.create_task(executor.do_inference(SECOND, b"gate:c"))
        await wait_until(lambda: (tmp_path / "c.entered").exists(), "the gate was never entered")
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        (tmp_path / "c.open").touch()
        assert await executor.do_inference(SECOND, b"reconnected") == b"reconnected"

        # The failed method reports its own unavailability on both entries, never a reset.
        for entry in (executor.do_inference, runtime.do_inference):
            with pytest.raises(RuntimeError, match="temporarily unavailable"):
                await entry(JOURNAL, b"refused")
        # Overall health still reports the failure so supervision rebuilds it.
        assert not runtime.is_alive
        assert await runtime.recover_failed_runners()
        assert await executor.do_inference(JOURNAL, b"recovered") == b"recovered"
        assert [data for _, data in journal(tmp_path, SECOND)] == [
            "first-use",
            "in-process",
            "gate:c",
            "reconnected",
        ]
        assert [data for _, data in journal(tmp_path)] == ["pid", "recovered"]
    finally:
        if executor is not None:
            await executor.close()
        await runtime.close()


async def test_cancelled_client_releases_its_channel_without_receiving_a_stale_result(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    runtime = service(tmp_path, JournalRunner)
    executor = None
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executor = InferenceExecutor(runtime.endpoint)
        pid = await executor.do_inference(JOURNAL, b"pid")

        caller = asyncio.create_task(executor.do_inference(JOURNAL, b"gate:c"))
        await wait_until(lambda: (tmp_path / "c.entered").exists(), "the gate was never entered")
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        (tmp_path / "c.open").touch()
        # The service consumes the dispatched response; the next caller gets only its own.
        assert await executor.do_inference(JOURNAL, b"next") == b"next"
        assert await executor.do_inference(JOURNAL, b"pid") == pid
        assert runtime.is_alive
        assert [data for _, data in journal(tmp_path)] == ["pid", "gate:c", "next", "pid"]
    finally:
        if executor is not None:
            await executor.close()
        await runtime.close()


async def test_partial_start_failure_reaps_started_runners_and_releases_the_endpoint(
    tmp_path: Path, socket_root: Path
) -> None:
    before, fds = children(), descriptors()
    runtime = service(tmp_path, EchoRunner, FailingInitRunner, JournalRunner)
    with pytest.raises(RuntimeError, match="RuntimeError") as failed:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
    assert "private model path" not in str(failed.value)
    assert [(view.method, view.startup_state, view.ready) for view in runtime.snapshot()] == [
        (ECHO, "ready", False),
        (FailingInitRunner.INFERENCE_METHOD, "failed", False),
        (JOURNAL, "pending", False),
    ]
    # The runner after the failure was never spawned.
    assert journal(tmp_path) == [] and not (tmp_path / f"{JOURNAL}.journal").exists()
    with pytest.raises(RuntimeError, match="not ready"):
        _ = runtime.endpoint
    assert_released(socket_root, before, fds)


async def test_cancelled_start_reaps_ready_and_initializing_runners(
    tmp_path: Path, socket_root: Path
) -> None:
    before = children()
    runtime = service(tmp_path, EchoRunner, SlowInitRunner, close_timeout=0.5)
    starting = asyncio.create_task(runtime.start())
    await wait_until(
        lambda: [view.startup_state for view in runtime.snapshot()] == ["ready", "initializing"],
        "the second runner never began initializing",
    )
    starting.cancel()
    # The slow child would initialize for 60 seconds; cancellation converges well before that.
    async with asyncio.timeout(HANG_GUARD):
        with pytest.raises(asyncio.CancelledError):
            await starting
    assert [view.startup_state for view in runtime.snapshot()] == ["ready", "cancelled"]
    assert_released(socket_root, before, None)


async def test_runner_close_failure_still_reaps_every_runner_and_releases_the_endpoint(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    before, fds = children(), descriptors()
    runtime = service(tmp_path, EchoRunner, FailingCloseRunner, JournalRunner)
    async with asyncio.timeout(HANG_GUARD):
        await runtime.start()
    owned_endpoints.add(runtime.endpoint)
    executor = InferenceExecutor(runtime.endpoint)
    for method in (ECHO, FailingCloseRunner.INFERENCE_METHOD, JOURNAL):
        assert await executor.do_inference(method, method.encode()) == method.encode()
    await executor.close()

    with pytest.raises(ExceptionGroup) as failed:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.close()
    # Diagnostics name the method and the failing frame, never the runner's message.
    assert failed.group_contains(RuntimeError, match=r"inference_runner_samples:\d+ in close")
    assert "test.failing_close" in str(failed.value.exceptions[0])
    assert "private close detail" not in repr(failed.value.exceptions)
    assert not runtime.is_alive
    assert_released(socket_root, before, fds)


async def test_repeated_start_stop_reclaims_processes_descriptors_and_endpoint(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    before, fds = children(), descriptors()
    for cycle in range(3):
        runtime = service(tmp_path, EchoRunner, JournalRunner)
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        endpoint = runtime.endpoint
        owned_endpoints.add(endpoint)

        # A rival in the same process fails without releasing the owner's endpoint.
        rival = service(tmp_path, EchoRunner)
        with pytest.raises(RuntimeError, match="already configured"):
            await rival.start()
        assert os.environ[INFERENCE_ENDPOINT_ENV] == endpoint and runtime.is_alive

        executor = InferenceExecutor(endpoint)
        assert (
            await executor.do_inference(ECHO, f"echo:{cycle}".encode()) == f"echo:{cycle}".encode()
        )
        assert (
            await executor.do_inference(JOURNAL, f"cycle:{cycle}".encode())
            == f"cycle:{cycle}".encode()
        )
        await executor.close()
        async with asyncio.timeout(HANG_GUARD):
            await runtime.close()
        assert not Path(endpoint).exists()
        assert_released(socket_root, before, fds)
    assert [data for _, data in journal(tmp_path)] == ["cycle:0", "cycle:1", "cycle:2"]
    assert len({pid for pid, _ in journal(tmp_path)}) == 3
