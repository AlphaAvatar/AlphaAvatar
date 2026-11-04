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
"""Doctor's diagnostic session: the configured chain, fed fixed samples, measured at its edges.

The session is the one ``start`` would run: loaded by the public configuration services,
the plan's runners in an InferenceRuntime, the Engine from ``create_execution``. Only the
transport is Doctor's (``transport``), and the workspace is temporary. Model downloads are
off in this process and its runners while the session runs. External services, often
billed, are reached only with ``host.doctor.external_services``. Steps have deadlines inside
one budget; whatever was started is closed in reverse after success, failure, timeout or
interruption, and what closing could not reclaim is reported.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import shutil
import tempfile
import time
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from alphaavatar.core.cleanup import wait_for_cleanup

from . import samples
from .enums import CheckStatus, ScenarioOutcome
from .measure import TurnObservation, scenario
from .schemas import Check, Metric, RunnerResult, ScenarioResult
from .transport import DiagnosticSink, DiagnosticSource, LogTimings

if TYPE_CHECKING:
    from alphaavatar.agents.runtime.inference import InferenceRuntime
    from alphaavatar.host.configs import ApplicationConfig, ConfigSource

SESSION_SECONDS = 180.0  # Runners from the cache, then plugins and readiness
TURN_SECONDS = 60.0  # One scenario turn, from its first input to its completed response
TOTAL_SECONDS = 480.0  # Everything, closing excluded: each close has its own bounds
# Both switch off the model resolvers' downloads; the second also Hugging Face libraries'.
_OFFLINE = ("ALPHAAVATAR_MODEL_OFFLINE", "HF_HUB_OFFLINE")
_DEVICE = "doctor-participant"
_VISION_STAGES = frozenset(
    (
        "frames.selected",
        "model.request",
        "model.first_event",
        "text.first",
        "text.complete",
        "answer",
    )
)
_POLL = 0.02


@dataclass(frozen=True, slots=True)
class Plan:
    """What the configuration enables, and the turns that exercise it."""

    voice: samples.Task | None  # The spoken scenario, with the picture when vision is on
    audio_input: bool
    vision: bool
    audio_output: bool
    visual_output: bool
    session_type: str

    @property
    def tasks(self) -> tuple[samples.Task, ...]:
        return (*(self.voice,) * (self.voice is not None), samples.TEXT)


def plan(config: ApplicationConfig) -> Plan:
    avatar = config.avatar
    audio_input = avatar.voice.vad.plugin is not None and avatar.voice.stt.plugin is not None
    audio_output = avatar.voice.tts.plugin is not None
    vision = avatar.vision.enabled and avatar.vision.input_mode.value != "text"
    # A voice session also speaks, so start refuses one without TTS; text sessions do not.
    voice = audio_input and audio_output
    task = (samples.VOICE_VISION if vision else samples.VOICE) if voice else None
    session_type = ("video" if vision else "audio") if voice else "chat"
    return Plan(
        task,
        audio_input,
        vision,
        audio_output and voice,
        avatar.character.plugin is not None,
        session_type,
    )


def start_services(config: ApplicationConfig) -> list[str]:
    """Services the runners reach while they start: vector stores embed a probe text."""
    avatar, found = config.avatar, []
    for name in ("memory", "persona"):
        if getattr(avatar, name).plugin == "default":
            found.append(f"{name} vector store embeddings")
    mcp = avatar.tools.mcp
    if mcp.enabled and mcp.plugin == "default" and mcp.servers:
        found.append("mcp tool index embeddings")
    return found


def _blocked(config: ApplicationConfig, services: Sequence[str]) -> str | None:
    if services and not config.host.doctor.external_services:
        return f"not authorized: {', '.join(services)}"
    return None


def starts(config: ApplicationConfig, services: Sequence[str]) -> bool:
    """Whether the session step starts anything: the session itself when it is allowed, or
    else the runners alone, when starting them reaches no external service."""
    from alphaavatar.agents.runtime.inference import plan_inference_runners

    if _blocked(config, services) is None:
        return True
    return not start_services(config) and bool(plan_inference_runners(config.avatar))


def unstarted(
    config: ApplicationConfig, source: ConfigSource, services: Sequence[str]
) -> dict[str, Check]:
    """The session's checks when it starts nothing: why, and what would allow it."""
    from .doctor import _command

    run = _Run(config, source, (), asyncio.Event())
    if found := start_services(config):
        run.unstarted = f"starting them reaches {', '.join(found)}, which needs authorization"
    else:
        run.unstarted = "no runner selected"
    return run.checks(_command("doctor", source), _blocked(config, services), services)


async def diagnose_session(
    config: ApplicationConfig,
    source: ConfigSource,
    overrides: Sequence[str],
    *,
    services: Sequence[str],
    stop: asyncio.Event | None = None,
) -> dict[str, Check]:
    """``session.start``, ``models.runners``, ``session.scenarios`` and ``session.cleanup``.

    ``services`` names the external services the configuration reaches; see ``starts``.
    """
    from .doctor import _command

    run = _Run(config, source, overrides, stop or asyncio.Event())
    run.deadline = asyncio.get_running_loop().time() + TOTAL_SECONDS
    doctor = _command("doctor", source)
    blocked = _blocked(config, services)
    workspace = tempfile.mkdtemp(prefix="alphaavatar-doctor-")
    saved = {name: os.environ.get(name) for name in _OFFLINE}
    os.environ.update(dict.fromkeys(_OFFLINE, "1"))
    children = {process.pid for process in mp.active_children()}
    try:
        with LogTimings() as logs:
            run.logs = logs
            await run.execute(workspace, blocked)
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        try:
            shutil.rmtree(workspace)
        except Exception as error:
            run.problems.append(
                f"temporary workspace {workspace} not removed: {type(error).__name__}"
            )
        left = sorted({process.pid for process in mp.active_children()} - children)
        if left:
            run.problems.append(f"processes still running: {', '.join(map(str, left))}")
    return run.checks(doctor, blocked, services)


class _Run:
    def __init__(
        self,
        config: ApplicationConfig,
        source: ConfigSource,
        overrides: Sequence[str],
        stop: asyncio.Event,
    ) -> None:
        self.config, self.source, self.overrides, self.stop = config, source, overrides, stop
        self.plan = plan(config)
        self.logs: LogTimings | None = None
        self.deadline = 0.0  # Set when the session step runs, on its event loop's clock.
        self.unstarted: str | None = None  # Why no runner starts, when that is decided first
        self.counters: tuple[Any, ...] = ()  # The runtime's own counters, before it closed
        self.problems: list[str] = []
        self.runtime: InferenceRuntime | None = None
        self.runners: list[RunnerResult] = []
        self.runner_error: tuple[str, ...] = ()
        self.started = False  # The runners
        self.session: Metric | None = None  # Readiness of the original configuration's session
        self.session_error: tuple[str, str, tuple[str, ...]] | None = None
        self.results: list[ScenarioResult] = []
        self.closed = 0
        self.interrupted = False

    # Budget

    def _remaining(self, limit: float) -> float:
        return max(0.0, min(limit, self.deadline - asyncio.get_running_loop().time()))

    async def _bounded(self, operation: Awaitable[Any], limit: float) -> tuple[str, Any]:
        """``done``, ``timeout`` or ``interrupted``, and the result or the error."""
        task = asyncio.ensure_future(operation)
        waiter = asyncio.create_task(self.stop.wait())
        try:
            await asyncio.wait(
                (task, waiter), timeout=self._remaining(limit), return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            waiter.cancel()
            if not task.done():
                task.cancel()
            # The operation's own cleanup finishes before this returns, even when cancelled.
            await wait_for_cleanup(
                asyncio.ensure_future(asyncio.gather(task, waiter, return_exceptions=True))
            )
        if task.cancelled():
            return ("interrupted" if self.stop.is_set() else "timeout"), None
        if (error := task.exception()) is not None:
            return "done", error
        return "done", task.result()

    # Steps

    async def execute(self, workspace: str, blocked: str | None) -> None:
        from alphaavatar.host.configs import load_application

        overrides = [*self.overrides, f"avatar.workspace_root={workspace}"]
        config = load_application(self.source, overrides)
        if blocked is not None and start_services(config):
            return  # Starting the runners would already reach an unauthorized service.
        try:
            await self._start_runners(config, workspace)
            if blocked is not None or self.runtime is None:
                return
            observations = await self._session(
                config, self.plan.session_type, self.plan.tasks, "original"
            )
            self.results += [_measure(item) for item in observations]
            await self._degrade(overrides)
        finally:
            if self.runtime is not None:
                self.counters = self.runtime.snapshot()
                try:
                    await self.runtime.close()
                except Exception as error:
                    self.problems += _lines("inference runtime close", error)
                self.closed += 1

    async def _start_runners(self, config: ApplicationConfig, workspace: str) -> None:
        from alphaavatar.agents.runtime.inference import (
            InferenceRuntime,
            RunnerLaunch,
            plan_inference_runners,
            snapshot_inference_config,
        )

        runtime = self.runtime = InferenceRuntime(
            plan_inference_runners(config.avatar),
            mp_ctx=mp.get_context("spawn"),
            launch=RunnerLaunch(
                workspace,
                str(config.paths.cache.models_dir),
                config=snapshot_inference_config(config.avatar),
            ),
            config=config.avatar.runtime.inference,
        )
        state, error = await self._bounded(runtime.start(), SESSION_SECONDS)
        self.started = state == "done" and error is None
        self.interrupted |= state == "interrupted"
        if state == "timeout":
            self.runner_error = (f"the runners did not start within {SESSION_SECONDS:g} s",)
        elif error is not None:
            self.runner_error = _diagnostic(error)
        for status in runtime.snapshot():
            self.runners.append(_runner(status, self.runner_error))
        if not self.started:
            await self._close_runtime()

    async def _close_runtime(self) -> None:
        if self.runtime is None:
            return
        runtime, self.runtime = self.runtime, None
        try:
            await runtime.close()
        except Exception as error:
            self.problems += _lines("inference runtime close", error)
        self.closed += 1

    async def _session(
        self,
        config: ApplicationConfig,
        session_type: str,
        tasks: Sequence[samples.Task],
        configuration: str,
    ) -> list[TurnObservation]:
        from alphaavatar.host.application.bootstrap import create_execution
        from alphaavatar.host.sessions.schemas import SessionContext

        access = SessionContext(
            device_id=_DEVICE,
            agent_device_id="doctor-avatar",
            room_name="doctor",
            metadata={"session_id": f"doctor-{uuid4().hex}", "session_type": session_type},
        )
        began = time.monotonic_ns()
        state, built = await self._bounded(create_execution(config, access), SESSION_SECONDS)
        self.interrupted |= state == "interrupted"
        if state != "done" or isinstance(built, BaseException):
            reason = state if state != "done" else "assembly failed"
            details = _diagnostic(built) if isinstance(built, BaseException) else ()
            self._unrun(tasks, configuration, f"session {reason}", details)
            if configuration == "original":
                self.session_error = (f"session {reason}", configuration, details)
            return []
        execution = built
        runtime = execution.runtime
        perception = runtime.perception
        sink = DiagnosticSink(runtime.output)
        timing = config.avatar.runtime.perception
        source = DiagnosticSource(
            perception,
            device_id=_DEVICE,
            frame_ms=timing.audio_frame_size_ms,
            video_interval_sec=timing.video_publish_interval_sec,
        )
        failed = None
        observations: list[TurnObservation] = []
        try:
            await sink.start()
            state, error = await self._bounded(execution.start(), SESSION_SECONDS)
            self.interrupted |= state == "interrupted"
            if state != "done" or error is not None:
                details = _diagnostic(error) if error is not None else ()
                self._unrun(
                    tasks,
                    configuration,
                    f"session start {state if state != 'done' else 'failed'}",
                    details,
                )
                if configuration == "original":
                    self.session_error = ("session start failed", configuration, details)
                return []
            source.start(audio=session_type != "chat", screen=session_type == "video")
            execution.engine.notify_ready()
            if configuration == "original":
                self.session = Metric(
                    "session_ready",
                    round((time.monotonic_ns() - began) / 1e6, 3),
                    "ms",
                    "session assembly began",
                    "Engine ready",
                    "runtime, plugins and Engine of the diagnostic session",
                )
            failed = asyncio.create_task(execution.wait_failed(), name="doctor_session_failed")
            for task in tasks:
                if self.stop.is_set() or not self._remaining(TURN_SECONDS):
                    reason = "interrupted" if self.stop.is_set() else "budget exhausted"
                    self._unrun((task,), configuration, f"not run: {reason}", ())
                    continue
                if task.speech is not None:
                    try:
                        samples.speech(task.speech)
                    except Exception as error:
                        stage = f"fixed sample {task.speech} unavailable"
                        self._unrun((task,), configuration, stage, _diagnostic(error))
                        continue
                observations.append(
                    await self._turn(execution, source, sink, task, configuration, failed)
                )
        finally:
            if failed is not None:
                failed.cancel()
                await asyncio.gather(failed, return_exceptions=True)
            source.stop()
            for label, close in (("output sink", sink.stop), ("session", execution.aclose)):
                try:
                    await close()
                except Exception as error:
                    self.problems += _lines(label, error)
            self.closed += 1
        return observations

    async def _turn(
        self,
        execution: Any,
        source: DiagnosticSource,
        sink: DiagnosticSink,
        task: samples.Task,
        configuration: str,
        failed: asyncio.Task[None],
    ) -> TurnObservation:
        logs = self.logs
        marks = len(sink.records), len(logs.records)
        done = asyncio.Event()
        playing = None
        start_ns = None
        deadline = asyncio.get_running_loop().time() + self._remaining(TURN_SECONDS)
        if task.speech is not None:
            picture = samples.card_picture() if task.screen else None
            playing = asyncio.create_task(
                source.play(samples.speech(task.speech), picture, done), name="doctor_play"
            )
        else:
            state, accepted = await self._bounded(
                source.type(execution.engine, task.text), TURN_SECONDS
            )
            start_ns = accepted if state == "done" and isinstance(accepted, int) else None
        turn_id, ended = None, None
        while True:
            if self.stop.is_set():
                ended = "interrupted"
                break
            if failed.done():
                ended = "session_failed"
                break
            if asyncio.get_running_loop().time() >= deadline:
                ended = "timeout"
                break
            records = logs.records[marks[1] :]
            if turn_id is None:
                turn_id = next(
                    (r.fields.get("turn_id") for r in records if r.name == "input.committed"), None
                )
            if turn_id is not None and _finished(turn_id, records, sink.records[marks[0] :]):
                break
            await asyncio.sleep(_POLL)
        done.set()
        timeline = None
        if playing is not None:
            timeline = await playing
            start_ns = timeline.voiced_end_ns
        await asyncio.sleep(0.1)  # Trailing receipts and records of the same turn.
        self.interrupted |= ended == "interrupted"
        trace = execution.runtime.perception.input_trace
        return TurnObservation(
            task=task,
            configuration=configuration,
            start_ns=start_ns,
            timeline=timeline,
            turn_id=turn_id,
            records=sink.records[marks[0] :],
            logs=logs.records[marks[1] :],
            trace=trace.snapshot().to_dict()["records"],
            identity=trace.identity,
            audio_output=configuration != "degraded: text output" and self.plan.audio_output,
            ended=ended,
            dropped=sink.dropped,
            queues=dict(sink.queues),
        )

    async def _degrade(self, overrides: list[str]) -> None:
        """The existing fallbacks, each in a session of its own, when the original needs one."""
        from alphaavatar.host.configs import load_application

        results = {result.name: result for result in self.results}
        voice_vision = results.get("voice_vision")
        trials = []
        # Heard, then stopped where pictures matter: selection, the model or its answer.
        if (
            voice_vision is not None
            and voice_vision.outcome == ScenarioOutcome.FAILED
            and voice_vision.blocked_stage in _VISION_STAGES
        ):
            # Vision unavailable: the audio session start runs for a camera-less participant.
            trials.append(
                ("degraded: vision off", ["vision.enabled=false"], "audio", (samples.VOICE,))
            )
        spoken = [r for r in self.results if r.name in ("voice", "voice_vision")]
        if any(r.blocked_stage == "audio.first" for r in spoken + [results.get("text")] if r):
            trials.append(("degraded: text output", [], "chat", (samples.TEXT,)))
        for configuration, changes, session_type, tasks in trials:
            if self.stop.is_set() or not self._remaining(SESSION_SECONDS):
                self._unrun(tasks, configuration, "not run: budget exhausted", ())
                continue
            config = load_application(self.source, [*overrides, *changes])
            observations = await self._session(config, session_type, tasks, configuration)
            self.results += [_measure(item) for item in observations]

    def _unrun(
        self,
        tasks: Sequence[samples.Task],
        configuration: str,
        stage: str,
        details: tuple[str, ...],
    ) -> None:
        interrupted = "interrupted" in stage
        for task in tasks:
            self.results.append(
                ScenarioResult(
                    task.name,
                    ScenarioOutcome.INTERRUPTED
                    if interrupted
                    else ScenarioOutcome.CONDITIONS_UNMET,
                    f"Not run: {stage}",
                    configuration,
                    blocked_stage=stage,
                    details=details,
                    task=task.prompt,
                )
            )

    # Report

    def checks(self, doctor: str, blocked: str | None, services: Sequence[str]) -> dict[str, Check]:
        return {
            "session.start": self._start_check(doctor, blocked, services),
            "models.runners": self._runner_check(doctor, blocked),
            "session.scenarios": self._scenario_check(doctor, blocked),
            "session.cleanup": self._cleanup_check(),
        }

    def _start_check(self, doctor: str, blocked: str | None, services: Sequence[str]) -> Check:
        if blocked is not None:
            return Check(
                "session.start",
                CheckStatus.SKIP,
                "Not run: the session would reach external services, and "
                "host.doctor.external_services is false",
                tuple(services),
                f"To allow these calls, which may be billed: set host.doctor.external_services: "
                f"true in the host profile, or run `{doctor} host.doctor.external_services=true`",
            )
        if not self.started:
            return Check(
                "session.start",
                CheckStatus.FAIL,
                "Not run: the runners did not start; see models.runners",
                action="Fix what models.runners names, then run doctor again",
            )
        if self.session_error is not None:
            stage, configuration, details = self.session_error
            return Check(
                "session.start",
                CheckStatus.FAIL,
                f"The diagnostic session did not start: {stage}",
                details,
                "Fix the reported component, then run doctor again",
            )
        metrics = (self.session,) if self.session is not None else ()
        ready = f"{self.session.value:.0f} ms" if self.session is not None else "unknown"
        return Check(
            "session.start",
            CheckStatus.PASS,
            f"A temporary session with the configured plugins was ready in {ready}",
            metrics=metrics,
        )

    def _runner_check(self, doctor: str, blocked: str | None) -> Check:
        from alphaavatar.agents.utils.files.model.model_files import models_offline

        from .doctor import _dev

        if not self.runners:
            reason = self.unstarted or ("no runner selected" if self.started else "not reached")
            return Check("models.runners", CheckStatus.SKIP, f"Not started: {reason}")
        failed = [runner for runner in self.runners if runner.status == CheckStatus.FAIL]
        pending = [runner for runner in self.runners if runner.status == CheckStatus.SKIP]
        if not failed and not pending:
            slowest = max(self.runners, key=lambda r: r.startup_seconds or 0.0)
            return Check(
                "models.runners",
                CheckStatus.PASS,
                f"{len(self.runners)} runners started from the cache, offline; slowest "
                f"{slowest.method} in {slowest.startup_seconds or 0:.2f} s",
                tuple(self._counted()),
                runners=tuple(self.runners),
                metrics=tuple(self._queues()),
            )
        missing = any("FileNotFoundError" in line for line in self.runner_error)
        status = CheckStatus.WARN if missing and not models_offline() else CheckStatus.FAIL
        first = failed[0].method if failed else "a runner"
        action = (
            f"Start `{_dev(self.source)}` once with network access to download the missing "
            "model, then run doctor again"
            if missing
            else "Fix what the error names (model file, package, device), then run doctor again"
        )
        return Check(
            "models.runners",
            status,
            f"{first} did not start{': its model is not in the cache' if missing else ''}; "
            f"{len(pending)} not reached",
            self.runner_error,
            action,
            runners=tuple(self.runners),
        )

    def _queues(self) -> list[Metric]:
        """Each runner's queue wait and execution, as its process summarizes them."""
        found: dict[str, list[dict]] = {}
        for record in self.logs.records if self.logs is not None else ():
            if record.name == "inference.summary":
                found.setdefault(record.fields.get("method"), []).append(record.fields)
        metrics = []
        for method, summaries in found.items():
            calls = sum(int(item.get("calls", 0)) for item in summaries)
            for name, key in (
                ("queue_wait_max", "queue_max_ms"),
                ("execution_max", "execution_max_ms"),
            ):
                metrics.append(
                    Metric(
                        name,
                        round(max(float(item.get(key, 0.0)) for item in summaries), 3),
                        "ms",
                        "request queued" if name == "queue_wait_max" else "request dispatched",
                        "request dispatched" if name == "queue_wait_max" else "result returned",
                        f"runner {method}, as its process summarizes it",
                        calls,
                        note="peak queue depth is not observed",
                    )
                )
        return metrics

    def _counted(self) -> list[str]:
        lines = []
        for status in self.counters:
            counts = {
                name: getattr(status, name)
                for name in ("rejected", "queue_timeouts", "execution_timeouts", "restarts")
                if getattr(status, name)
            }
            if counts:
                lines.append(
                    f"{status.method}: " + ", ".join(f"{k} {v}" for k, v in counts.items())
                )
        return lines

    def _scenario_check(self, doctor: str, blocked: str | None) -> Check:
        results = list(self.results)
        names = {result.name for result in results}
        for task in self.plan.tasks:
            if task.name not in names:
                stage = (
                    blocked if blocked is not None else "the runners or the session did not start"
                )
                results.append(
                    ScenarioResult(
                        task.name,
                        ScenarioOutcome.CONDITIONS_UNMET,
                        f"Not run: {stage}",
                        "original",
                        blocked_stage="authorization" if blocked is not None else "session.start",
                        task=task.prompt,
                    )
                )
        if not self.plan.vision:
            results.append(
                _absent("voice_vision", ScenarioOutcome.NOT_ENABLED, "vision is off or text only")
            )
        if self.plan.voice is None and self.plan.audio_input:
            results.append(
                _absent(
                    "voice",
                    ScenarioOutcome.CONDITIONS_UNMET,
                    "a voice session needs TTS, as start does",
                )
            )
        results.append(
            _absent(
                "image_input",
                ScenarioOutcome.NO_COVERAGE,
                "no input transport delivers images to a session yet",
            )
        )
        results.append(
            _absent(
                "visual_output",
                ScenarioOutcome.NO_COVERAGE
                if self.plan.visual_output
                else ScenarioOutcome.NOT_ENABLED,
                "the Character renders in its own RTC participant; its frames carry no Turn"
                if self.plan.visual_output
                else "no Character is configured",
            )
        )
        original = [r for r in results if r.configuration == "original"]
        measured = [
            r for r in results if r.outcome in (ScenarioOutcome.PASSED, ScenarioOutcome.FAILED)
        ]
        failed = [r for r in original if r.outcome == ScenarioOutcome.FAILED]
        degraded = [r for r in measured if r.configuration != "original"]
        count = {outcome: sum(r.outcome == outcome for r in results) for outcome in ScenarioOutcome}
        summary = ", ".join(
            f"{n} {outcome.value.replace('_', ' ')}" for outcome, n in count.items() if n
        )
        if degraded:
            summary += f"; degraded: {', '.join(f'{r.name} {r.outcome.value}' for r in degraded)}"
        if failed:
            status, action = (
                CheckStatus.FAIL,
                "See each failed scenario's blocked stage and evidence",
            )
        elif any(r.outcome == ScenarioOutcome.PASSED for r in original):
            status, action = CheckStatus.PASS, None
        else:
            status = CheckStatus.SKIP
            action = None if blocked is None else "See session.start"
        return Check("session.scenarios", status, summary, action=action, scenarios=tuple(results))

    def _cleanup_check(self) -> Check:
        if self.problems:
            return Check(
                "session.cleanup",
                CheckStatus.FAIL,
                "Closing the diagnostic session left something behind",
                tuple(self.problems),
                "End any process left named inference:<method>, then report this with the "
                "output of `alphaavatar doctor --json`",
            )
        if not self.closed:
            return Check(
                "session.cleanup", CheckStatus.SKIP, "Nothing started, so nothing to reclaim"
            )
        return Check(
            "session.cleanup",
            CheckStatus.PASS,
            f"{self.closed} owned parts closed: sessions and executor before the runtime; "
            "runner processes, sockets and the temporary workspace reclaimed",
        )


def _finished(turn_id: str, logs: list, records: list) -> bool:
    end = next(
        (r for r in logs if r.name == "run.finished" and r.fields.get("turn_id") == turn_id), None
    )
    if end is None:
        return False
    if end.fields.get("state") != "completed":
        return True
    outputs = {
        r.output_id
        for r in records
        if r.turn_id == turn_id
        and r.lane == "assistant"
        and r.kind in ("text_chunk", "audio_frame")
    }
    # Complete, or ended by an interruption that names them as its targets.
    complete = {r.output_id for r in records if r.kind == "control" and r.control == "complete"}
    complete |= {target for r in records if r.control == "interrupt" for target in r.targets}
    return outputs <= complete


def _measure(observation: TurnObservation) -> ScenarioResult:
    """A scenario from its observation; a measurement that fails stays this scenario's."""
    try:
        return scenario(observation)
    except Exception as error:
        return ScenarioResult(
            observation.task.name,
            ScenarioOutcome.FAILED,
            "The observation could not be measured",
            observation.configuration,
            blocked_stage="measurement",
            details=_diagnostic(error),
            task=observation.task.prompt,
        )


def _absent(name: str, outcome: ScenarioOutcome, reason: str) -> ScenarioResult:
    return ScenarioResult(name, outcome, reason[0].upper() + reason[1:], "original")


def _runner(status: Any, error: tuple[str, ...]) -> RunnerResult:
    if status.startup_state == "ready":
        return RunnerResult(
            status.method,
            CheckStatus.PASS,
            "started",
            startup_seconds=status.startup_elapsed_seconds,
        )
    if status.startup_state in ("failed", "cancelled"):
        return RunnerResult(
            status.method,
            CheckStatus.FAIL,
            f"{status.startup_state}: {status.error_type}",
            error,
            status.startup_elapsed_seconds,
        )
    return RunnerResult(
        status.method, CheckStatus.SKIP, "not reached: an earlier runner did not start"
    )


def _diagnostic(error: BaseException) -> tuple[str, ...]:
    from alphaavatar.host.configs import format_failure

    text = format_failure(error)
    if type(error) is RuntimeError:
        # The runtime relays a runner's own diagnostic: error types and code locations.
        text += f"\n{error}"
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def _lines(label: str, error: BaseException) -> list[str]:
    return [f"{label} did not close cleanly", *_diagnostic(error)]
