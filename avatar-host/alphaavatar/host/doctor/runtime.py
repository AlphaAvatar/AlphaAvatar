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
"""Doctor's runtime checks: the selected runners that offer a probe, one at a time.

A runner offers one through ``InferenceRunner.probe``; nothing registers it. Each probe runs
the planned runner class in its own InferenceRuntime with one worker and
reaches it through an InferenceExecutor, with the launch snapshot start uses: requests take
a session's path and data protocol. Nothing else in the plan starts, so no vector store,
MCP index or other runner. Models come from the configured cache: a missing one is reported,
never fetched, and runner processes start with model downloads switched off. Their workspace
is a temporary directory. Closing always runs, after a failure, timeout or interruption too:
the executor, then the runtime, then the temporary directory.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import shutil
import statistics
import tempfile
import time
from collections import Counter
from typing import TYPE_CHECKING

from alphaavatar.core.cleanup import wait_for_cleanup

from .doctor import _command, _dev, probes
from .enums import CheckStatus
from .schemas import Check, RunnerResult

if TYPE_CHECKING:
    from alphaavatar.agents.runtime.inference import InferenceRunner, RunnerProbe
    from alphaavatar.host.configs import ApplicationConfig, ConfigSource

PROBE_SECONDS = 120.0  # One runner: its start and every request.
RUNTIME_SECONDS = 300.0  # Every runner; each close is bounded by runtime.inference itself.
LATER_REQUESTS = 5
# Both switch off the model resolvers' downloads; the second also Hugging Face libraries'.
_OFFLINE = ("ALPHAAVATAR_MODEL_OFFLINE", "HF_HUB_OFFLINE")
_SCOPE = (
    "Fixed samples, one runner at a time, one worker each: the figures describe these "
    "probes only, not whether the voice pipeline keeps up; parallel workers are not verified"
)


async def runtime_checks(
    config: ApplicationConfig, source: ConfigSource, *, stop: asyncio.Event | None = None
) -> tuple[Check, Check]:
    """``runtime.models`` and ``runtime.cleanup`` for a loaded configuration."""
    from alphaavatar.agents.runtime.inference import plan_inference_runners
    from alphaavatar.agents.utils.files.model.model_files import models_offline

    runners = plan_inference_runners(config.avatar)
    found = probes(runners)
    models_dir = str(config.paths.cache.models_dir)
    # Start loads models the same way: offline, a missing model fails it rather than waits.
    offline = models_offline()
    doctor = f"{_command('doctor', source)} --runtime"
    results: dict[str, RunnerResult | None] = {}
    for method in runners:
        probe = found.get(method)
        if probe is None:
            results[method] = RunnerResult(
                method, CheckStatus.SKIP, "No local probe: not started, so not verified"
            )
        elif (missing := probe.missing(models_dir)) is not None:
            fetch = f"Start `{_dev(source)}` once with network access to download it"
            if offline:
                fetch += " (model loading is offline here, so start fails without it)"
            results[method] = RunnerResult(
                method,
                CheckStatus.FAIL if offline else CheckStatus.WARN,
                missing,
                action=f"{fetch}; then run `{doctor}` again",
                model=probe.model,
            )
        else:
            results[method] = None  # Run below, in plan order.
    queued = [
        (runners[method], found[method]) for method, result in results.items() if result is None
    ]
    started, problems = await _run(queued, config, results, doctor, stop) if queued else (0, [])
    return _models(results, source, doctor), _cleanup(started, problems)


async def _run(
    queued: list[tuple[type[InferenceRunner], RunnerProbe]],
    config: ApplicationConfig,
    results: dict[str, RunnerResult | None],
    doctor: str,
    stop: asyncio.Event | None,
) -> tuple[int, list[str]]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + RUNTIME_SECONDS
    children = {process.pid for process in mp.active_children()}
    problems: list[str] = []
    started = 0
    workspace = tempfile.mkdtemp(prefix="alphaavatar-doctor-")
    # Spawned runners inherit the environment at start; it is restored after the last one.
    saved = {name: os.environ.get(name) for name in _OFFLINE}
    os.environ.update(dict.fromkeys(_OFFLINE, "1"))
    try:
        for runner, probe in queued:
            method = runner.INFERENCE_METHOD
            budget = min(PROBE_SECONDS, deadline - loop.time())
            if stop is not None and stop.is_set():
                results[method] = RunnerResult(
                    method, CheckStatus.SKIP, "Not run: interrupted", model=probe.model
                )
            elif budget <= 0:
                results[method] = RunnerResult(
                    method,
                    CheckStatus.SKIP,
                    f"Not run: the {RUNTIME_SECONDS:g} s budget of the runtime checks ran out",
                    action=f"Run `{doctor}` again to check the rest",
                    model=probe.model,
                )
            else:
                started += 1
                results[method], closing = await _probe(
                    runner, probe, config, workspace, budget, doctor, stop
                )
                problems += closing
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        try:
            shutil.rmtree(workspace)
        except Exception as error:
            problems += [f"temporary workspace {workspace} not removed", *_lines(error)]
        # Closing reaps each runner; any process still here would outlive Doctor.
        left = sorted({process.pid for process in mp.active_children()} - children)
        if left:
            problems.append(f"runner processes still running: {', '.join(map(str, left))}")
    return started, problems


async def _probe(
    runner: type[InferenceRunner],
    probe: RunnerProbe,
    config: ApplicationConfig,
    workspace: str,
    budget: float,
    doctor: str,
    stop: asyncio.Event | None,
) -> tuple[RunnerResult, list[str]]:
    from alphaavatar.agents.runtime.inference import (
        InferenceExecutor,
        InferenceRuntime,
        RunnerLaunch,
        snapshot_inference_config,
    )

    method = runner.INFERENCE_METHOD
    # One worker: whether the model works, not how several share this machine.
    inference = config.avatar.runtime.inference.model_copy(update={"methods": {}})
    runtime: InferenceRuntime | None = None
    executor: InferenceExecutor | None = None
    stage, initialize, violation = "while starting", None, None
    timings: list[float] = []

    async def measure() -> str:
        nonlocal runtime, executor, stage, initialize, violation
        runtime = InferenceRuntime(
            {method: runner},
            mp_ctx=mp.get_context("spawn"),
            launch=RunnerLaunch(
                workspace,
                str(config.paths.cache.models_dir),
                config=snapshot_inference_config(config.avatar),
            ),
            config=inference,
        )
        await runtime.start()
        (status,) = runtime.snapshot()
        initialize = status.startup_elapsed_seconds
        executor = InferenceExecutor(runtime.endpoint, inference)
        request = probe.request
        output = ""
        for index in range(1 + LATER_REQUESTS):
            stage = "on a later request" if index else "on the first request"
            begun = time.perf_counter()
            answer = await executor.do_inference(method, request)
            timings.append(time.perf_counter() - begun)
            stage = "checking an answer"
            try:
                output = probe.check(answer)  # Every answer, not only the last one.
            except ValueError as error:
                violation = str(error)
                raise
        return output

    async def close() -> list[str]:
        work.cancel()
        waiter.cancel()
        await asyncio.gather(work, waiter, return_exceptions=True)
        closing = []
        for name, owner in (("executor", executor), ("runtime", runtime)):
            if owner is None:
                continue
            try:
                await owner.close()
            except Exception as error:
                closing += [f"{method}: the {name} did not close cleanly", *_lines(error)]
        return closing

    work = asyncio.create_task(measure(), name=f"doctor_probe:{method}")
    waiter = asyncio.create_task((stop or asyncio.Event()).wait(), name="doctor_probe_stop")
    try:
        await asyncio.wait((work, waiter), timeout=budget, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Even when this call is cancelled: the executor first, then the runtime.
        closing = await wait_for_cleanup(asyncio.create_task(close(), name="doctor_probe_close"))

    measured = {
        "model": probe.model,
        "initialize_seconds": initialize,
        "inference_seconds": tuple(timings),
        "audio_seconds": probe.audio_seconds,
        "device": probe.device,
    }
    again = f"then run `{doctor}` again"
    if work.cancelled():
        if stop is not None and stop.is_set():
            return RunnerResult(
                method, CheckStatus.SKIP, f"Interrupted {stage}", **measured
            ), closing
        return RunnerResult(
            method,
            CheckStatus.FAIL,
            f"{probe.model}: no result within {budget:.3g} s, {stage}",
            action=f"Check what else loads this machine, {again}",
            **measured,
        ), closing
    if (error := work.exception()) is not None:
        if violation is not None:
            summary = f"{probe.model}: the answer breaks the probe's contract: {violation}"
        else:
            summary = f"{probe.model}: failed {stage}"
        return RunnerResult(
            method,
            CheckStatus.FAIL,
            summary,
            _lines(error),
            f"Fix what the error names (model file, package, device), {again}",
            **measured,
        ), closing
    later = timings[1:]
    steady = statistics.median(later)
    summary = (
        f"{probe.model}: started in {_duration(initialize)}; first request "
        f"{_duration(timings[0])}, then {_duration(steady)} (median of {len(later)})"
    )
    rtf = None
    if probe.audio_seconds:
        rtf = steady / probe.audio_seconds
        summary += f"; RTF {rtf:.3f} on {_duration(probe.audio_seconds)} of audio"
    if probe.device is not None:
        summary += f"; on {probe.device}"
    return RunnerResult(
        method, CheckStatus.PASS, summary, real_time_factor=rtf, output=work.result(), **measured
    ), closing


def _models(results: dict[str, RunnerResult | None], source: ConfigSource, doctor: str) -> Check:
    runners = tuple(result for result in results.values() if result is not None)
    if not runners:
        return Check("runtime.models", CheckStatus.SKIP, "No runner selected, so no model to run")
    count = Counter(runner.status for runner in runners)
    words = {
        CheckStatus.PASS: "passed",
        CheckStatus.FAIL: "failed",
        CheckStatus.WARN: "warned",
        CheckStatus.SKIP: "not verified",
    }
    summary = f"{len(runners)} selected runners: " + ", ".join(
        f"{count[status]} {word}" for status, word in words.items() if count[status]
    )
    ran = any(r.initialize_seconds is not None or r.inference_seconds for r in runners)
    details = (_SCOPE,) if ran else ()
    if count[CheckStatus.FAIL] or count[CheckStatus.WARN]:
        status = CheckStatus.FAIL if count[CheckStatus.FAIL] else CheckStatus.WARN
        action = f"Follow each runner's next step, then run `{doctor}` again"
    elif count[CheckStatus.PASS]:
        return Check("runtime.models", CheckStatus.PASS, summary, details, runners=runners)
    elif any(runner.model is not None for runner in runners):
        status, action = CheckStatus.SKIP, f"Run `{doctor}` again to check the rest"  # Not run.
    else:
        status, action = (
            CheckStatus.SKIP,
            f"`{_dev(source)}` initializes them before it accepts a session",
        )
    return Check("runtime.models", status, summary, details, action, runners)


def _cleanup(started: int, problems: list[str]) -> Check:
    if problems:
        return Check(
            "runtime.cleanup",
            CheckStatus.FAIL,
            "Closing the runtime checks left something behind",
            tuple(problems),
            "End any process left named inference:<method>, then report this with the output "
            "of `alphaavatar doctor --runtime --json`",
        )
    if not started:
        return Check(
            "runtime.cleanup", CheckStatus.SKIP, "No runner started, so nothing to reclaim"
        )
    plural = "s" * (started != 1)
    return Check(
        "runtime.cleanup",
        CheckStatus.PASS,
        f"{started} runtime{plural} closed: executor, runner process and socket; "
        "temporary workspace removed",
    )


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    return f"{seconds * 1000:.1f} ms" if seconds < 1 else f"{seconds:.2f} s"


def _lines(error: BaseException) -> tuple[str, ...]:
    from alphaavatar.host.configs import format_failure

    text = format_failure(error)
    if type(error) is RuntimeError:
        # The runtime relays the runner's own diagnostic: error types and code locations.
        text += f"\n{error}"
    return tuple(line.strip() for line in text.splitlines() if line.strip())
