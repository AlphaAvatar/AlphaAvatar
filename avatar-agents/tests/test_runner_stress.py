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
"""Synthetic Runner pressure: one bounded round by default, longer with ``--stress-seconds``.

Numbers printed here are synthetic local results, never device or production performance.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
import signal
import statistics
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable
from multiprocessing import resource_tracker
from pathlib import Path

import pytest
from inference_runner_samples import EchoRunner, JournalRunner, ParallelRunner, SecondJournalRunner

from alphaavatar.agents.configs.runtime_config import InferenceConfig
from alphaavatar.agents.runtime.inference import (
    INFERENCE_ENDPOINT_ENV,
    InferenceExecutor,
    InferenceRunner,
    InferenceRuntime,
    RunnerLaunch,
)

pytestmark = pytest.mark.stress

HANG_GUARD = 60
SESSIONS, REQUESTS = 4, 8
ECHO, JOURNAL = EchoRunner.INFERENCE_METHOD, JournalRunner.INFERENCE_METHOD
METHODS = (ECHO, JOURNAL, SecondJournalRunner.INFERENCE_METHOD)
PARALLEL, WORK_MS = ParallelRunner.INFERENCE_METHOD, 5


def service(root: Path, *runners: type[InferenceRunner], **options: object) -> InferenceRuntime:
    return InferenceRuntime(
        {runner.INFERENCE_METHOD: runner for runner in runners},
        mp_ctx=mp.get_context("spawn"),
        launch=RunnerLaunch(
            str(root), str(root / "models"), config=json.dumps({"test": {"root": str(root)}})
        ),
        config=InferenceConfig(
            initialize_timeout=HANG_GUARD,
            queue_timeout=HANG_GUARD,
            request_timeout=HANG_GUARD,
            close_timeout=1,
            **options,
        ),
    )


async def rounds(seconds: float) -> AsyncIterator[int]:
    deadline, index = time.monotonic() + seconds, 0
    while True:
        yield index
        index += 1
        if time.monotonic() >= deadline:
            return


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.002)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


def journal(root: Path, method: str) -> list[tuple[int, str]]:
    path = root / f"{method}.journal"
    lines = path.read_text().splitlines() if path.exists() else []
    return [(int(pid), data) for pid, data in (line.split(" ", 1) for line in lines)]


def children() -> set[int]:
    return {process.pid for process in mp.active_children()}


def descriptors() -> Counter[str] | None:
    directory = Path("/proc/self/fd")
    if not directory.is_dir():
        return None
    resource_tracker.ensure_running()
    # Count per target: two leaked descriptors may share one target such as a pipe.
    targets: Counter[str] = Counter()
    for entry in directory.iterdir():
        try:
            targets[os.readlink(entry)] += 1
        except FileNotFoundError:
            pass
    return targets


def milliseconds(samples: list[float]) -> str:
    return f"p50_ms={1000 * statistics.median(samples):.2f} max_ms={1000 * max(samples):.2f}"


async def test_concurrent_sessions_and_methods_never_lose_duplicate_or_misroute_results(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object], stress_seconds: float
) -> None:
    runtime = service(tmp_path, EchoRunner, JournalRunner, SecondJournalRunner)
    executors: list[InferenceExecutor] = []
    sent: Counter[str] = Counter()
    mismatched: list[tuple[str, bytes | None]] = []
    latencies: list[float] = []
    inflight, peak = Counter[str](), Counter[str]()

    async def call(executor: InferenceExecutor, method: str, payload: str) -> None:
        inflight[method] += 1
        peak[method] = max(peak[method], inflight[method])
        started = time.perf_counter()
        try:
            result = await executor.do_inference(method, payload.encode())
        finally:
            inflight[method] -= 1
        latencies.append(time.perf_counter() - started)
        sent[method] += 1
        if result != payload.encode():
            mismatched.append((payload, result))

    async def sequence(executor: InferenceExecutor, method: str, prefix: str) -> None:
        # One session's connection is serial per method; sessions and methods run concurrently.
        for item in range(REQUESTS):
            await call(executor, method, f"{prefix}:{item}")

    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executors.extend(InferenceExecutor(runtime.endpoint) for _ in range(SESSIONS))
        completed = 0
        async for index in rounds(stress_seconds):
            async with asyncio.timeout(HANG_GUARD):
                async with asyncio.TaskGroup() as group:
                    for session, executor in enumerate(executors):
                        for method in METHODS:
                            prefix = f"{index}:{session}:{method}"
                            group.create_task(sequence(executor, method, prefix))
            completed += 1
    finally:
        for executor in executors:
            await executor.close()
        await runtime.close()

    expected = completed * SESSIONS * REQUESTS
    print(
        f"\n[stress] concurrent rounds={completed} requests={sum(sent.values())} "
        f"mismatched={len(mismatched)} peak_inflight={dict(peak)} {milliseconds(latencies)}"
    )
    assert mismatched == []
    assert sent == dict.fromkeys(METHODS, expected)
    # Every journaled request executed exactly once, in one runner process per method.
    for method in METHODS[1:]:
        records = journal(tmp_path, method)
        assert len(records) == len({data for _, data in records}) == expected
        assert len({pid for pid, _ in records}) == 1


async def test_runner_failure_churn_recovers_without_replaying_attempted_work(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object], stress_seconds: float
) -> None:
    before = children()
    # Recoveries are always further apart than this window, so the budget never runs out.
    runtime = service(tmp_path, JournalRunner, EchoRunner, restart_window_seconds=1e-3)
    executor = None
    recoveries: list[float] = []
    pids: list[int] = []
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executor = InferenceExecutor(runtime.endpoint)
        assert await executor.do_inference(ECHO, b"connected") == b"connected"
        async for index in rounds(stress_seconds):
            pids.append(int(await executor.do_inference(JOURNAL, b"pid")))
            lost = asyncio.create_task(executor.do_inference(JOURNAL, f"gate:r{index}".encode()))
            await wait_until((tmp_path / f"r{index}.entered").exists, "the gate was never entered")
            os.kill(pids[-1], signal.SIGKILL)
            with pytest.raises(RuntimeError):
                await lost
            started = time.perf_counter()
            async with asyncio.timeout(HANG_GUARD):
                assert await runtime.recover_failed_runners()
            recoveries.append(time.perf_counter() - started)
            # The healthy method's established connection progressed across the failure.
            payload = f"echo:{index}".encode()
            assert await executor.do_inference(ECHO, payload) == payload
    finally:
        if executor is not None:
            await executor.close()
        await runtime.close()

    records = journal(tmp_path, JOURNAL)
    gated = [(pid, data) for pid, data in records if data.startswith("gate:")]
    print(
        f"\n[stress] churn kills={len(pids)} recoveries={len(recoveries)} "
        f"recovery_{milliseconds(recoveries)}"
    )
    assert len(set(pids)) == len(pids) == len(recoveries)
    # Each attempted request ran once, in the process that was then killed; none was replayed.
    assert gated == [(pid, f"gate:r{index}") for index, pid in enumerate(pids)]
    assert children() - before == set()


async def test_repeated_runtime_start_stop_reclaims_processes_descriptors_and_endpoint(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object], stress_seconds: float
) -> None:
    before, fds = children(), descriptors()
    cycles: list[float] = []
    async for index in rounds(stress_seconds):
        started = time.perf_counter()
        runtime = service(tmp_path, EchoRunner, JournalRunner)
        try:
            async with asyncio.timeout(HANG_GUARD):
                await runtime.start()
            owned_endpoints.add(runtime.endpoint)
            executor = InferenceExecutor(runtime.endpoint)
            for method in (ECHO, JOURNAL):
                payload = f"{method}:{index}".encode()
                assert await executor.do_inference(method, payload) == payload
            await executor.close()
        finally:
            await runtime.close()
        cycles.append(time.perf_counter() - started)
        assert children() - before == set()
        assert INFERENCE_ENDPOINT_ENV not in os.environ
        assert list(socket_root.iterdir()) == []
        after = descriptors()
        if fds is not None and after is not None:
            assert after - fds == Counter()
    print(f"\n[stress] start_stop cycles={len(cycles)} cycle_{milliseconds(cycles)}")
    assert len(journal(tmp_path, JOURNAL)) == len(cycles)


@pytest.mark.parametrize("workers", [1, 2])
async def test_parallel_workers_stay_bounded_owned_and_reclaimed_under_session_load(
    workers: int,
    tmp_path: Path,
    socket_root: Path,
    owned_endpoints: set[object],
    stress_seconds: float,
) -> None:
    before, fds = children(), descriptors()
    methods = {PARALLEL: {"workers": workers}}
    runtime = service(tmp_path, ParallelRunner, EchoRunner, methods=methods)
    config = InferenceConfig(methods=methods)
    executors: list[InferenceExecutor] = []
    latencies: list[float] = []
    mismatched: list[bytes] = []
    errors: Counter[str] = Counter()

    async def call(executor: InferenceExecutor, payload: bytes) -> None:
        started = time.perf_counter()
        try:
            result = await executor.do_inference(PARALLEL, payload)
        except Exception as error:
            errors[type(error).__name__] += 1
            return
        latencies.append(time.perf_counter() - started)
        if result != payload:
            mismatched.append(payload)

    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executors.extend(InferenceExecutor(runtime.endpoint, config) for _ in range(SESSIONS))
        started, sent = time.perf_counter(), 0
        async for index in rounds(stress_seconds):
            # Every session issues its requests at once; channels and the pool bound them.
            async with asyncio.timeout(HANG_GUARD):
                async with asyncio.TaskGroup() as group:
                    for session, executor in enumerate(executors):
                        for item in range(REQUESTS):
                            payload = f"work:{WORK_MS}:{index}:{session}:{item}".encode()
                            group.create_task(call(executor, payload))
                            sent += 1
        elapsed = time.perf_counter() - started
        (status,) = [view for view in runtime.snapshot() if view.method == PARALLEL]
    finally:
        for executor in executors:
            await executor.close()
        await runtime.close()

    spans = [
        (int(pid), float(start), float(end), payload)
        for pid, start, end, payload in (
            line.split(" ", 3) for line in (tmp_path / f"{PARALLEL}.spans").read_text().splitlines()
        )
    ]
    # Peak runner-side concurrency from the recorded spans, across processes.
    edges = sorted([(start, 1) for _, start, _, _ in spans] + [(end, -1) for _, _, end, _ in spans])
    running = peak = 0
    for _, step in edges:
        running += step
        peak = max(peak, running)
    executions = [end - start for _, start, end, _ in spans]
    waits = sorted(latency - statistics.median(executions) for latency in latencies)
    after = descriptors()
    leaked = sum((after - fds).values()) if fds is not None and after is not None else 0
    print(
        f"\n[stress] parallel workers={workers} requests={sent} errors={dict(errors)} "
        f"mismatched={len(mismatched)} throughput_rps={sent / elapsed:.1f} "
        f"latency_{milliseconds(latencies)} execution_{milliseconds(executions)} "
        f"queue_est_p50_ms={1000 * statistics.median(waits):.2f} peak_running={peak} "
        f"processes={len({pid for pid, *_ in spans})} rejected={status.rejected} "
        f"timeouts={status.queue_timeouts + status.execution_timeouts} "
        f"leaked_children={len(children() - before)} leaked_fds={leaked}"
    )
    assert errors == Counter() and mismatched == []
    assert sorted(payload for *_, payload in spans) == sorted(
        f"work:{WORK_MS}:{index}:{session}:{item}"
        for index in range(sent // (SESSIONS * REQUESTS))
        for session in range(SESSIONS)
        for item in range(REQUESTS)
    )
    # Never more than the configured workers at once, and all of them used under load.
    assert peak == workers == len({pid for pid, *_ in spans})
    assert (status.rejected, status.queue_timeouts, status.execution_timeouts) == (0, 0, 0)
    assert children() - before == set() and leaked == 0
