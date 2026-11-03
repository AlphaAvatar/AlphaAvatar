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
"""Configured Runner parallelism through real Executors, IPC and spawned runner processes.

Concurrency is proven with gates the runners enter and the test opens, never with sleeps
or speed ratios.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
import signal
from pathlib import Path

import numpy as np
import pytest
from inference_checks import HANG_GUARD, assert_released, children, descriptors, wait_until
from inference_runner_samples import (
    EchoRunner,
    JournalRunner,
    ParallelRunner,
    SecondParallelRunner,
    SileroProtocolRunner,
)
from pydantic import ValidationError

from alphaavatar.agents.configs.runtime_config import InferenceConfig
from alphaavatar.agents.runtime.inference import (
    InferenceExecutor,
    InferenceRunner,
    InferenceRuntime,
    RunnerLaunch,
)
from alphaavatar.agents.runtime.inference.schemas import InferenceRunnerStatus
from alphaavatar.core.media import AudioFrame
from alphaavatar.plugins.voice.vad.silero import SileroVADOptions, SileroVADStream

PARALLEL, SECOND = ParallelRunner.INFERENCE_METHOD, SecondParallelRunner.INFERENCE_METHOD
ECHO, JOURNAL = EchoRunner.INFERENCE_METHOD, JournalRunner.INFERENCE_METHOD
SILERO = SileroProtocolRunner.INFERENCE_METHOD


def limits(workers: dict[str, int] | None = None, **options: object) -> InferenceConfig:
    defaults = {
        "initialize_timeout": HANG_GUARD,
        "queue_timeout": HANG_GUARD,
        "request_timeout": HANG_GUARD,
        "close_timeout": 1,
    }
    return InferenceConfig(
        methods={method: {"workers": count} for method, count in (workers or {}).items()},
        **(defaults | options),
    )


def service(root: Path, config: InferenceConfig, *runners: type[InferenceRunner]):
    return InferenceRuntime(
        {runner.INFERENCE_METHOD: runner for runner in runners},
        mp_ctx=mp.get_context("spawn"),
        launch=RunnerLaunch(
            str(root), str(root / "models"), config=json.dumps({"test": {"root": str(root)}})
        ),
        config=config,
    )


def view(runtime: InferenceRuntime, method: str) -> InferenceRunnerStatus:
    (status,) = [status for status in runtime.snapshot() if status.method == method]
    return status


async def entered(root: Path, *names: str) -> None:
    await wait_until(
        lambda: all((root / f"{name}.entered").exists() for name in names),
        f"gates {names} were never all entered at once",
    )


def release(root: Path, *names: str) -> None:
    for name in names:
        (root / f"{name}.open").touch()


def journal(root: Path, method: str = PARALLEL) -> dict[str, list[int]]:
    """Payload -> the pids that executed it; one entry per execution."""
    path = root / f"{method}.journal"
    runs: dict[str, list[int]] = {}
    for line in path.read_text().splitlines() if path.exists() else []:
        pid, data = line.split(" ", 1)
        runs.setdefault(data, []).append(int(pid))
    return runs


async def test_a_replicable_runner_stays_serial_until_configured(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    config = limits()
    runtime = service(tmp_path, config, ParallelRunner)
    executors: list[InferenceExecutor] = []
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executors.extend(InferenceExecutor(runtime.endpoint, config) for _ in range(2))
        first = asyncio.create_task(executors[0].do_inference(PARALLEL, b"gate:a"))
        await entered(tmp_path, "a")
        second = asyncio.create_task(executors[1].do_inference(PARALLEL, b"gate:b"))
        await wait_until(lambda: view(runtime, PARALLEL).waiting == 1, "b never queued")
        # Default parallelism is one worker: the second request waits in the service.
        assert (view(runtime, PARALLEL).workers, view(runtime, PARALLEL).executing) == (1, 1)
        assert not (tmp_path / "b.entered").exists()

        release(tmp_path, "a")
        assert await first == b"gate:a"
        await entered(tmp_path, "b")
        release(tmp_path, "b")
        assert await second == b"gate:b"
        runs = journal(tmp_path)
        assert runs["gate:a"] == runs["gate:b"]  # The same single process.
    finally:
        for executor in executors:
            await executor.close()
        await runtime.close()


async def test_two_workers_run_one_sessions_requests_at_once_and_never_exceed_the_limit(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    config = limits({PARALLEL: 2})
    runtime = service(tmp_path, config, ParallelRunner)
    session = other = None
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        session, other = (InferenceExecutor(runtime.endpoint, config) for _ in range(2))
        assert (view(runtime, PARALLEL).workers, view(runtime, PARALLEL).ready_workers) == (2, 2)

        a = asyncio.create_task(session.do_inference(PARALLEL, b"gate:a"))
        b = asyncio.create_task(session.do_inference(PARALLEL, b"gate:b"))
        # Barrier: both requests of one Executor are inside runners at the same time.
        await entered(tmp_path, "a", "b")
        runs = journal(tmp_path)
        assert len({*runs["gate:a"], *runs["gate:b"]}) == 2  # Two distinct processes.

        c = asyncio.create_task(other.do_inference(PARALLEL, b"gate:c"))
        await wait_until(lambda: view(runtime, PARALLEL).waiting == 1, "c never queued")
        assert view(runtime, PARALLEL).executing == 2
        assert not (tmp_path / "c.entered").exists()  # A third never runs beside the two.

        # Out of order on the same Executor: b answers first, with its own result.
        release(tmp_path, "b")
        assert await b == b"gate:b"
        assert not a.done()
        # The waiting request goes to the worker that freed, not behind the busy one.
        await entered(tmp_path, "c")
        assert journal(tmp_path)["gate:c"] == runs["gate:b"]
        release(tmp_path, "a", "c")
        assert (await a, await c) == (b"gate:a", b"gate:c")

        status = view(runtime, PARALLEL)
        assert (status.executing, status.waiting, status.rejected, status.ready) == (0, 0, 0, True)
        assert all(len(pids) == 1 for pids in journal(tmp_path).values())
    finally:
        for executor in (session, other):
            if executor is not None:
                await executor.close()
        await runtime.close()


async def test_results_stay_with_their_callers_across_executors_and_methods(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    config = limits({PARALLEL: 2, SECOND: 2})
    runtime = service(tmp_path, config, ParallelRunner, SecondParallelRunner, EchoRunner)
    executors: list[InferenceExecutor] = []
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executors.extend(InferenceExecutor(runtime.endpoint, config) for _ in range(3))
        calls = {
            (method, f"gate:{index}-{method}-{call}"): asyncio.create_task(
                executor.do_inference(method, f"gate:{index}-{method}-{call}".encode())
            )
            for index, executor in enumerate(executors)
            for method in (PARALLEL, SECOND)
            for call in range(2)
        }
        for method in (PARALLEL, SECOND):
            await wait_until(
                lambda method=method: (
                    view(runtime, method).executing,
                    view(runtime, method).waiting,
                )
                == (2, 4),
                f"{method} never held two running and four waiting requests",
            )
        # A serial method is not delayed by the occupied parallel ones.
        for index, executor in enumerate(executors):
            assert await executor.do_inference(ECHO, f"echo:{index}".encode()) == (
                f"echo:{index}".encode()
            )

        # Open gates newest first, so completions arrive out of submission order.
        release(tmp_path, *(payload.removeprefix("gate:") for _, payload in reversed(calls)))
        for (_, payload), task in calls.items():
            assert await task == payload.encode()
        for method in (PARALLEL, SECOND):
            runs = journal(tmp_path, method)
            expected = {payload for called, payload in calls if called == method}
            assert set(runs) == expected and all(len(pids) == 1 for pids in runs.values())
            assert len({pid for pids in runs.values() for pid in pids}) == 2
    finally:
        for executor in executors:
            await executor.close()
        await runtime.close()


async def test_full_queue_rejects_and_cancelled_requests_never_run_or_leak_results(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    # Capacity counts executing and waiting requests together: 2 running + 1 waiting.
    config = limits({PARALLEL: 2}, max_pending=3)
    runtime = service(tmp_path, config, ParallelRunner)
    executors: list[InferenceExecutor] = []
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        first, second, third = (InferenceExecutor(runtime.endpoint, config) for _ in range(3))
        executors.extend((first, second, third))
        a = asyncio.create_task(first.do_inference(PARALLEL, b"gate:a"))
        b = asyncio.create_task(first.do_inference(PARALLEL, b"gate:b"))
        await entered(tmp_path, "a", "b")
        workers = {*journal(tmp_path)["gate:a"], *journal(tmp_path)["gate:b"]}
        queued = asyncio.create_task(second.do_inference(PARALLEL, b"queued"))
        await wait_until(lambda: view(runtime, PARALLEL).waiting == 1, "never queued")
        with pytest.raises(RuntimeError, match="at capacity"):
            await third.do_inference(PARALLEL, b"overflow")
        assert view(runtime, PARALLEL).rejected == 1

        # A caller leaving while queued withdraws the request from the service.
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        await wait_until(lambda: view(runtime, PARALLEL).waiting == 0, "never withdrawn")
        # A caller leaving after dispatch: the worker finishes it, and nobody receives it.
        a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await a
        assert view(runtime, PARALLEL).executing == 2

        release(tmp_path, "a", "b")
        assert await b == b"gate:b"
        await wait_until(lambda: view(runtime, PARALLEL).executing == 0, "a never settled")
        # Every channel answers only its own new request; no worker was retired.
        assert await first.do_inference(PARALLEL, b"after-a") == b"after-a"
        assert await second.do_inference(PARALLEL, b"after-queued") == b"after-queued"
        assert await third.do_inference(PARALLEL, b"after-overflow") == b"after-overflow"
        runs = journal(tmp_path)
        assert "queued" not in runs and "overflow" not in runs
        assert len(runs["gate:a"]) == len(runs["gate:b"]) == 1
        assert {pid for pids in runs.values() for pid in pids} == workers
        assert view(runtime, PARALLEL).ready
    finally:
        for executor in executors:
            await executor.close()
        await runtime.close()


async def test_queue_and_execution_timeouts_withdraw_or_retire_without_replay(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    config = limits({PARALLEL: 2}, queue_timeout=0.5, request_timeout=3.0)
    runtime = service(tmp_path, config, ParallelRunner)
    session = other = None
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        session, other = (InferenceExecutor(runtime.endpoint, config) for _ in range(2))
        stuck = asyncio.create_task(session.do_inference(PARALLEL, b"gate:stuck"))
        b = asyncio.create_task(session.do_inference(PARALLEL, b"gate:b"))
        await entered(tmp_path, "stuck", "b")

        # The queue budget runs out while both workers are busy: withdrawn, never executed.
        with pytest.raises(RuntimeError, match="expired waiting for a worker"):
            await other.do_inference(PARALLEL, b"late")
        assert view(runtime, PARALLEL).queue_timeouts == 1

        release(tmp_path, "b")
        assert await b == b"gate:b"
        # The execution budget retires only the stuck worker; its request is not replayed.
        with pytest.raises(RuntimeError):
            await stuck
        status = view(runtime, PARALLEL)
        assert (status.execution_timeouts, status.ready_workers, status.ready) == (1, 1, False)
        # Degraded, not refused: the healthy worker keeps serving every session.
        assert not runtime.is_alive
        assert await other.do_inference(PARALLEL, b"degraded") == b"degraded"

        async with asyncio.timeout(HANG_GUARD):
            assert await runtime.recover_failed_runners()
        assert (view(runtime, PARALLEL).ready_workers, view(runtime, PARALLEL).restarts) == (2, 1)
        runs = journal(tmp_path)
        assert "late" not in runs and len(runs["gate:stuck"]) == 1
    finally:
        for executor in (session, other):
            if executor is not None:
                await executor.close()
        await runtime.close()


async def test_a_killed_worker_is_reaped_and_rebuilt_while_its_peer_keeps_serving(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    before = children()
    config = limits({PARALLEL: 2}, restart_limit=2)
    runtime = service(tmp_path, config, ParallelRunner)
    executor = None
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executor = InferenceExecutor(runtime.endpoint, config)
        lost = asyncio.create_task(executor.do_inference(PARALLEL, b"gate:lost"))
        kept = asyncio.create_task(executor.do_inference(PARALLEL, b"gate:kept"))
        await entered(tmp_path, "lost", "kept")
        (victim,), (peer,) = journal(tmp_path)["gate:lost"], journal(tmp_path)["gate:kept"]

        os.kill(victim, signal.SIGKILL)
        with pytest.raises(RuntimeError):
            await lost
        # The peer's request in flight is untouched, and new work goes to the peer.
        release(tmp_path, "kept")
        assert await kept == b"gate:kept"
        assert view(runtime, PARALLEL).ready_workers == 1 and not runtime.is_alive
        assert await executor.do_inference(PARALLEL, b"pid") == str(peer).encode()

        async with asyncio.timeout(HANG_GUARD):
            assert await runtime.recover_failed_runners()
        assert runtime.is_alive and view(runtime, PARALLEL).restarts == 1
        replacement = next(
            int(pid)
            for pid in (tmp_path / f"{PARALLEL}.inits").read_text().split()
            if int(pid) not in (victim, peer)
        )

        # A replacement that fails to initialize leaves the peer serving; the Host decides.
        (tmp_path / "init4.fail").touch()
        os.kill(replacement, signal.SIGKILL)
        await wait_until(lambda: view(runtime, PARALLEL).ready_workers == 1, "kill unseen")
        async with asyncio.timeout(HANG_GUARD):
            assert not await runtime.recover_failed_runners()
        assert view(runtime, PARALLEL).ready_workers == 1
        assert await executor.do_inference(PARALLEL, b"pid") == str(peer).encode()
        # The per-method budget is now spent: no further attempt, the peer still serves.
        (tmp_path / "init4.fail").unlink()
        async with asyncio.timeout(HANG_GUARD):
            assert not await runtime.recover_failed_runners()
        assert len((tmp_path / f"{PARALLEL}.inits").read_text().split()) == 4
        assert view(runtime, PARALLEL).restarts == 2
        assert await executor.do_inference(PARALLEL, b"still") == b"still"
        assert journal(tmp_path)["gate:lost"] == [victim]  # Attempted once, never replayed.
    finally:
        if executor is not None:
            await executor.close()
        await runtime.close()
    assert children() - before == set()


async def test_waiting_requests_fail_at_once_when_no_worker_is_left(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    config = limits({PARALLEL: 2})
    runtime = service(tmp_path, config, ParallelRunner)
    session = other = None
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        session, other = (InferenceExecutor(runtime.endpoint, config) for _ in range(2))
        running = [
            asyncio.create_task(session.do_inference(PARALLEL, f"gate:{name}".encode()))
            for name in ("a", "b")
        ]
        await entered(tmp_path, "a", "b")
        queued = asyncio.create_task(other.do_inference(PARALLEL, b"queued"))
        await wait_until(lambda: view(runtime, PARALLEL).waiting == 1, "never queued")
        for pids in journal(tmp_path).values():
            os.kill(pids[0], signal.SIGKILL)
        # Well inside the queue budget: the waiter learns now, not when its time runs out.
        async with asyncio.timeout(HANG_GUARD / 2):
            with pytest.raises(RuntimeError, match="temporarily unavailable"):
                await queued
        for task in running:
            with pytest.raises(RuntimeError):
                await task
        with pytest.raises(RuntimeError, match="temporarily unavailable"):
            await other.do_inference(PARALLEL, b"refused")
        async with asyncio.timeout(HANG_GUARD):
            assert await runtime.recover_failed_runners()
        assert await other.do_inference(PARALLEL, b"recovered") == b"recovered"
        assert "queued" not in journal(tmp_path) and "refused" not in journal(tmp_path)
    finally:
        for executor in (session, other):
            if executor is not None:
                await executor.close()
        await runtime.close()


@pytest.mark.parametrize("window", ["reaping", "starting"])
async def test_close_during_recovery_starts_no_worker_and_reclaims_every_one(
    window: str, tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    before = children()
    runtime = service(tmp_path, limits({PARALLEL: 2}), ParallelRunner)
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        for pid in (tmp_path / f"{PARALLEL}.inits").read_text().split():
            os.kill(int(pid), signal.SIGKILL)
        await wait_until(lambda: view(runtime, PARALLEL).ready_workers == 0, "kills unseen")
        if window == "starting":
            (tmp_path / "init3.hold").touch()
        recovering = asyncio.create_task(runtime.recover_failed_runners())
        if window == "reaping":
            # One loop turn: recovery passed its checks and now awaits the first dead worker.
            await asyncio.sleep(0)
        else:
            await entered(tmp_path, "init3")  # The first replacement is initializing.
        assert not recovering.done()

        async with asyncio.timeout(HANG_GUARD):
            await runtime.close()
            stopped = recovering.done()
            recovered = await recovering
        # Nothing survives close, now or later, and the caller is not cancelled.
        assert children() - before == set()
        assert (stopped, recovered) == (True, False)
        inits = (tmp_path / f"{PARALLEL}.inits").read_text().split()
        assert len(inits) == (2 if window == "reaping" else 3)
        assert view(runtime, PARALLEL).restarts == (0 if window == "reaping" else 1)
    finally:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.close()
    assert children() - before == set()


async def test_partial_start_failure_and_cancelled_initialization_release_every_worker(
    tmp_path: Path, socket_root: Path
) -> None:
    before, fds = children(), descriptors()
    (tmp_path / "init2.fail").touch()
    runtime = service(tmp_path, limits({PARALLEL: 2}), EchoRunner, ParallelRunner)
    with pytest.raises(RuntimeError, match="RuntimeError") as failed:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
    assert "private init detail" not in str(failed.value)
    status = view(runtime, PARALLEL)
    assert (status.startup_state, status.ready_workers, status.workers) == ("failed", 0, 2)
    assert_released(socket_root, before, fds)

    (tmp_path / "init2.fail").unlink()
    (tmp_path / f"{PARALLEL}.inits").unlink()
    (tmp_path / "init2.hold").touch()
    runtime = service(tmp_path, limits({PARALLEL: 2}), ParallelRunner)
    starting = asyncio.create_task(runtime.start())
    await entered(tmp_path, "init2")
    assert view(runtime, PARALLEL).startup_state == "initializing"
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(HANG_GUARD):
            await starting
    assert view(runtime, PARALLEL).startup_state == "cancelled"
    assert_released(socket_root, before, None)


async def test_close_is_idempotent_and_reclaims_every_worker_and_channel(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    before, fds = children(), descriptors()
    config = limits({PARALLEL: 2, SECOND: 2})
    for cycle in range(2):
        runtime = service(tmp_path, config, ParallelRunner, SecondParallelRunner)
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        executor = InferenceExecutor(runtime.endpoint, config)
        held = asyncio.create_task(executor.do_inference(PARALLEL, f"gate:h{cycle}".encode()))
        await entered(tmp_path, f"h{cycle}")
        for method in (PARALLEL, SECOND):
            payloads = [f"{method}:{cycle}:{call}".encode() for call in range(4)]
            calls = (executor.do_inference(method, payload) for payload in payloads)
            assert await asyncio.gather(*calls) == payloads
        await executor.close()
        with pytest.raises(asyncio.CancelledError):
            await held
        async with asyncio.timeout(HANG_GUARD):
            await runtime.close()
            await runtime.close()
        assert not runtime.is_alive
        assert_released(socket_root, before, fds)
    assert len((tmp_path / f"{PARALLEL}.inits").read_text().split()) == 4


async def test_parallel_configuration_is_validated_before_any_process_starts(
    tmp_path: Path, socket_root: Path
) -> None:
    for methods in (
        {PARALLEL: {"workers": 0}},
        {PARALLEL: {"workers": 9}},
        {PARALLEL: {"workers": "2"}},
        {PARALLEL: {"workers": 2.0}},
        {PARALLEL: {"workers": 2, "queue": 1}},
        {f" {PARALLEL}": {"workers": 2}},
    ):
        with pytest.raises(ValidationError):
            InferenceConfig(methods=methods)
    for options in (
        {"max_pending": 0},
        {"max_pending": 1, "methods": {PARALLEL: {"workers": 2}}},
        {"queue_timeout": 0},
        {"request_timeout": float("inf")},
        {"client_timeout": float("nan")},
        {"restart_limit": 101},
        {"inference": {}},
    ):
        with pytest.raises(ValidationError):
            InferenceConfig.model_validate(options)

    before = children()
    with pytest.raises(ValidationError) as unsupported:
        service(tmp_path, limits({JOURNAL: 2, "test.misspelled": 1}), JournalRunner)
    assert [error["loc"] for error in unsupported.value.errors()] == [
        ("runtime", "inference", "methods", "test.misspelled"),
        ("runtime", "inference", "methods", JOURNAL, "workers"),
    ]
    assert children() == before and list(socket_root.iterdir()) == []
    assert InferenceRuntime({PARALLEL: ParallelRunner}, config=limits({PARALLEL: 8})).methods == (
        PARALLEL,
    )


def frame(sample: int, windows: int = 1) -> AudioFrame:
    samples = 512 * windows
    return AudioFrame(
        sample_rate=16_000,
        num_channels=1,
        samples_per_channel=samples,
        data=np.full(samples, sample, dtype="<i2").tobytes(),
    )


async def test_concurrent_voice_sources_keep_their_own_state_results_and_cancellation(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    config = limits({SILERO: 2})
    runtime = service(tmp_path, config, SileroProtocolRunner)
    executor = None
    streams: list[SileroVADStream] = []
    try:
        async with asyncio.timeout(HANG_GUARD):
            await runtime.start()
        owned_endpoints.add(runtime.endpoint)
        # One session client, as in production, shared by every source's VAD stream.
        executor = InferenceExecutor(runtime.endpoint, config)
        options = SileroVADOptions(
            min_speech_duration=0.05,
            min_silence_duration=0.1,
            deactivation_threshold=0.35,
            smoothing_alpha=0.0,
            inference_timeout_sec=HANG_GUARD,
        )
        speaker, listener, held = (
            SileroVADStream(options=options, inference_executor=executor) for _ in range(3)
        )
        streams.extend((speaker, listener, held))
        events: dict[str, list] = {"speaker": [], "listener": []}

        async def collect(name: str, stream: SileroVADStream) -> None:
            async for event in stream:
                events[name].append(event)

        collectors = [
            asyncio.create_task(collect(name, stream))
            for name, stream in (("speaker", speaker), ("listener", listener))
        ]

        # One source's window holds a worker; the other sources share the second one.
        assert held.push_frame(frame(SileroProtocolRunner.HELD_SAMPLE))
        await entered(tmp_path, "voice")
        assert speaker.push_frame(frame(8000, windows=4))
        assert listener.push_frame(frame(0, windows=6))
        done = "inference_done"
        await wait_until(
            lambda: [sum(e.type.value == done for e in events[n]) for n in events] == [4, 6],
            "the free worker never served both sources",
        )

        # Cancelling the held source does not disturb the others or retire its worker.
        await held.aclose()
        release(tmp_path, "voice")
        assert speaker.push_frame(frame(0, windows=4))
        assert listener.push_frame(frame(0, windows=2))
        for stream in (speaker, listener):
            assert stream.end_input()
        async with asyncio.timeout(HANG_GUARD):
            await asyncio.gather(*collectors)

        kinds = {
            name: [e.type.value for e in items if e.type.value != done]
            for name, items in events.items()
        }
        assert kinds == {"speaker": ["start_of_speech", "end_of_speech"], "listener": []}
        # Each stream's recurrent state is its own history: speech counts 1000, quiet 1.
        assert np.all(speaker._state == 4 * 1000 + 4)
        assert np.all(listener._state == 8)
        assert view(runtime, SILERO).ready_workers == 2
        await wait_until(lambda: view(runtime, SILERO).executing == 0, "held never settled")
    finally:
        for stream in streams:
            await stream.aclose()
        if executor is not None:
            await executor.close()
        await runtime.close()
