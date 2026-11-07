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

It runs in Doctor's diagnostic process (``process``), on one snapshot of the configuration
moved onto Doctor's storage: a temporary workspace, with explicit local vector store paths
inside it (``isolate``). Its runtime starts once, as start starts it, and each round of its
one scenario runs in a session of its own from ``create_execution``; only the transport is
Doctor's (``transport``). Nothing else is tried: a failure is reported as it is. External
services, often billed, are reached only with ``host.doctor.external_services``; real Avatar
data Doctor cannot isolate, a remote vector store, is never written, so what needs it is
skipped: the two are separate bounds.
Each step starts only inside the remaining budget and keeps the state its wait ended in;
whatever was started is closed in reverse after success, failure, timeout or interruption,
and what closing could not reclaim is reported.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import statistics
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from alphaavatar.core.cleanup import wait_for_cleanup

from . import samples
from .enums import CheckStatus, ScenarioOutcome
from .measure import TURN_ENDED, TurnObservation, scenario, summarize
from .schemas import Check, Metric, RunnerResult, ScenarioResult, ServiceResult
from .transport import DiagnosticSink, DiagnosticSource, LogTimings, SourceTimeline

if TYPE_CHECKING:
    from alphaavatar.host.configs import ApplicationConfig, ConfigSource

SESSION_SECONDS = 180.0  # Runners from the cache, or a session's plugins and readiness
TURN_SECONDS = 60.0  # One scenario turn, from its first input to its outputs' end
TOTAL_SECONDS = 480.0  # Everything, closing excluded: each close has its own bounds
START_MARGIN_SECONDS = 30.0  # Past the runners' own timeouts, so theirs is what is reported
_DEVICE = "doctor-participant"
_POLL = 0.02


@dataclass(frozen=True, slots=True)
class Budget:
    session: float  # A session's assembly and readiness
    turn: float
    total: float
    runners: float = SESSION_SECONDS  # The runtime's start, model downloads included


def budget(initialize: float | None = None, turns: int = 3, runners: int = 1) -> Budget:
    """The diagnosis's bounds. The runtime starts as start starts it: its runners one after
    another, each within its ``initialize`` timeout, downloads included, so its own timeout
    is the error reported; this bound only catches a start that keeps to none. The whole has
    as much more, and a turn's bound for each turn past three."""
    start = max(SESSION_SECONDS, (initialize or 0.0) * max(1, runners) + START_MARGIN_SECONDS)
    extra = start - SESSION_SECONDS + max(0, turns - 3) * TURN_SECONDS
    return Budget(SESSION_SECONDS, TURN_SECONDS, TOTAL_SECONDS + extra, start)


@dataclass(frozen=True, slots=True)
class Plan:
    """The one scenario the configuration runs, in every round: with vision on, the card
    question over the picture, speech and frames in one request; with it off, the
    two-sentence question that shows whether a sentence was lost. A configuration that cannot
    hold a voice session runs none, and ``missing`` says why. The question asked, the budget
    and the run all read this one plan."""

    task: samples.Task | None
    vision: bool
    visual_output: bool
    configuration: str  # What the rounds run with, as the report labels them
    missing: str | None = None

    @property
    def tasks(self) -> tuple[samples.Task, ...]:
        return () if self.task is None else (self.task,)

    @property
    def session_type(self) -> str:
        return "video" if self.vision else "audio"


def plan(config: ApplicationConfig) -> Plan:
    avatar = config.avatar
    vision = avatar.vision.enabled and avatar.vision.input_mode.value != "text"
    # The samples are spoken, and a voice session also speaks, so start refuses one without TTS.
    lacking = [
        f"voice.{part}" for part in ("vad", "stt", "tts") if not getattr(avatar.voice, part).plugin
    ]
    task = None if lacking else samples.VOICE_VISION if vision else samples.VOICE
    missing = (
        f"its scenarios are spoken, and a voice session needs voice.vad, voice.stt and "
        f"voice.tts; this configuration has no {', '.join(lacking)}"
        if lacking
        else None
    )
    return Plan(task, vision, avatar.character.plugin is not None, configured(config), missing)


def configured(config: ApplicationConfig) -> str:
    """What a scenario's rounds run with: the selections its figures depend on."""
    avatar = config.avatar
    model = (avatar.loop.init_config or {}).get("model") or {}
    parts = [f"model {model['model']}"] if isinstance(model, dict) and model.get("model") else []
    for name in ("stt", "tts"):
        if (section := getattr(avatar.voice, name)).plugin:
            parts.append(f"{name} {section.plugin} {section.model}")
    vision = avatar.vision
    on = vision.enabled and vision.input_mode.value != "text"
    parts.append(
        f"vision {vision.input_mode.value}, max_frames {vision.max_frames}" if on else "vision off"
    )
    return " · ".join(parts)


# Configuration snapshots


def derive(config: ApplicationConfig, changes: Mapping[str, object]) -> ApplicationConfig:
    """The same snapshot with dotted ``changes``, validated again; no file or environment is
    read, so what was authorized is what starts."""
    from alphaavatar.host.configs import validate_application

    data = json.loads(config.payload)
    for key, value in changes.items():
        *parents, name = key.split(".")
        node = data
        for part in parents:
            node[part] = node.get(part) or {}
            node = node[part]
        node[name] = value
    return validate_application(data)


def _stores(config: ApplicationConfig) -> list[tuple[str, str, dict[str, Any]]]:
    """The selected plugins' vector stores: the plugin's namespace, its section, its store
    settings.

    A section with store settings has a store, whichever plugin it names: a store Doctor
    cannot account for is still never written.
    """
    from alphaavatar.agents.runtime.plugin import resolve_plugins

    stores = []
    plugins = resolve_plugins(config.avatar).plugins
    for location in config.avatar.plugin_factories():
        section = config.avatar.section(location)
        if location in plugins and (vdb := getattr(section, "vdb_config", None)) is not None:
            stores.append((plugins[location].namespace, location.rpartition(".")[0], vdb))
    return stores


def remote_stores(config: ApplicationConfig) -> list[str]:
    """The remote vector stores the configuration names: Doctor cannot move them."""
    from alphaavatar.agents.utils.vdb.config import vdb_backend

    return [
        f"{name}'s Qdrant store" for name, _, vdb in _stores(config) if vdb_backend(vdb) == "qdrant"
    ]


def unisolated(config: ApplicationConfig) -> list[str]:
    """Real Avatar data Doctor cannot keep apart from its own: the remote vector stores,
    unless the configuration says they are test stores."""
    return [] if config.host.doctor.test_stores else remote_stores(config)


def isolate(config: ApplicationConfig, workspace: str) -> tuple[ApplicationConfig, tuple[str, ...]]:
    """The snapshot on Doctor's storage: ``workspace`` as the Avatar workspace, and each
    explicit local vector store path moved inside it, where the default would be."""
    from alphaavatar.agents.utils.vdb.config import vdb_backend
    from alphaavatar.agents.workspace import WorkspacePaths

    changes: dict[str, object] = {"avatar.workspace_root": workspace}
    rebound = []
    indexes = WorkspacePaths.from_root(workspace).data.indexes
    for name, key, vdb in _stores(config):
        if vdb_backend(vdb) == "lancedb" and vdb.get("client_path"):
            # Where the plugin keeps the store by default: under its own storage name.
            path = indexes.namespace(name).backend("lancedb").root
            changes[f"{key}.vdb_config.client_path"] = str(path)
            rebound.append(f"{name}'s LanceDB path")
    return derive(config, changes), tuple(rebound)


# What may start


def start_services(config: ApplicationConfig) -> list[str]:
    """What the runners call as they start, as they declare it (``PROVIDERS``): a vector
    store embeds a probe text with its provider. Listed with the services the configuration
    names, before the diagnosis runs."""
    from alphaavatar.agents.runtime.inference import plan_inference_runners
    from alphaavatar.agents.runtime.plugin import AvatarModule

    found = []
    for method, runner in sorted(plan_inference_runners(config.avatar).items()):
        if runner.PROVIDERS:
            kinds = {AvatarModule(module) for module, _ in runner.PROVIDERS}
            what = "embeddings" if kinds == {AvatarModule.PROVIDER_EMBEDDING} else "model providers"
            found.append(f"{what} as {method} starts")
    return found


def _cached_bytes(root: Any) -> int:
    """The bytes of the model files under ``root``: what grows when a start downloads."""
    total = 0
    for path in Path(root).rglob("*") if Path(root).is_dir() else ():
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue  # Replaced as it was read: a download in progress.
    return total


def _size(count: int) -> str:
    for unit in ("bytes", "KB", "MB"):
        if count < 1000 or unit == "MB":
            return f"{count:,} {unit}" if unit == "bytes" else f"{count:,.1f} {unit}"
        count /= 1000
    return f"{count:,.1f} GB"


def _grown(grown: int) -> str:
    """How the model cache changed over the runtime's start: a net change, all a scan can
    tell. It is no download count: a file replaced or removed meanwhile offsets one."""
    return (
        f"the model cache grew by {_size(grown)} (net)"
        if grown > 0
        else ("the model cache did not grow (net)")
    )


def model_not_cached(details: Sequence[str]) -> bool:
    """Whether a runner's start failed for want of cached model files: the resolver's own
    error type (``ModelNotCached``) in its diagnostic, which the runtime's start wraps."""
    return any(line.strip() == "error: ModelNotCached" for line in details)


def probe_failed(details: Sequence[str]) -> bool:
    """Whether a vector store's start failed at its embedding probe, the provider's request:
    the probe's own error type (``EmbeddingProbeError``) in the start's diagnostic."""
    return any(line.strip() == "error: EmbeddingProbeError" for line in details)


def embedding_runners(config: ApplicationConfig) -> frozenset[str]:
    """The planned runners that reach providers as they start, such as a vector store's."""
    from alphaavatar.agents.runtime.inference import plan_inference_runners

    planned = plan_inference_runners(config.avatar)
    return frozenset(method for method, runner in planned.items() if runner.PROVIDERS)


def blocked(config: ApplicationConfig, services: Sequence[str]) -> str | None:
    """Why the diagnosis may not start: no scenario it can run, data it cannot isolate, or no
    authorization, which starting the runtime needs whatever it reaches: it may download
    model files too."""
    reasons = []
    if (missing := plan(config).missing) is not None:
        reasons.append(f"no scenario to run: {missing}")
    if stores := unisolated(config):
        reasons.append(f"real Avatar data cannot be isolated: {', '.join(stores)}")
    if not config.host.doctor.external_services:
        reasons.append("not authorized" + (f": {', '.join(services)}" if services else ""))
    return "; ".join(reasons) or None


def starts(config: ApplicationConfig, services: Sequence[str]) -> bool:
    """Whether the diagnosis starts anything: only once it is authorized and can isolate
    what it writes. Nothing starts partly: not even runners, whatever they reach."""
    return blocked(config, services) is None


def unstarted(
    config: ApplicationConfig, source: ConfigSource, services: Sequence[tuple[str, str]]
) -> dict[str, Check]:
    """The session's checks when it starts nothing: why, and what would allow it."""
    return _Run(config, source, services, asyncio.Event(), budget()).checks()


async def diagnose_session(
    config: ApplicationConfig,
    source: ConfigSource,
    services: Sequence[tuple[str, str]],
    rebound: Sequence[str],
    *,
    limits: Budget,
    stop: asyncio.Event,
    logs: LogTimings,
    rounds: int = 1,
    planned: Plan | None = None,
) -> dict[str, Check]:
    """The session's checks, ``services.external`` with them, from the isolated snapshot.

    Runs in the diagnostic process; ``services`` names and kinds the external services the
    configuration reaches, as ``doctor`` lists them, and ``planned`` is the plan the person
    agreed to. Its scenario runs ``rounds`` times, each time in a session of its own.
    """
    run = _Run(config, source, services, stop, limits, logs, rounds, planned)
    run.rebound = tuple(rebound)
    run.deadline = asyncio.get_running_loop().time() + limits.total
    children = {process.pid for process in mp.active_children()}
    try:
        await run.execute()
    finally:
        left = sorted({process.pid for process in mp.active_children()} - children)
        if left:
            run.problems.append(f"processes still running: {', '.join(map(str, left))}")
    return run.checks()


class _Run:
    def __init__(
        self,
        config: ApplicationConfig,
        source: ConfigSource,
        services: Sequence[tuple[str, str]],
        stop: asyncio.Event,
        limits: Budget,
        logs: LogTimings | None = None,
        rounds: int = 1,
        planned: Plan | None = None,
    ) -> None:
        self.config, self.source, self.stop, self.limits = config, source, stop, limits
        self.rounds = rounds
        self.ready: list[float] = []  # Each session's readiness, in milliseconds
        self.start: Metric | None = None  # The runtime's one start
        self.services = tuple(services)
        self.names = [name for name, _ in self.services]
        self.blocked = blocked(config, self.names)
        self.plan = planned or plan(config)
        self.logs = logs
        self.deadline = 0.0  # Set when the session step runs, on its event loop's clock.
        self.unstarted: str | None = None  # Why no runner starts, when that is decided first
        self.rebound: tuple[str, ...] = ()  # Local stores moved into the temporary workspace
        self.counters: list[Any] = []  # The runtime's own counters, before it closed
        self.problems: list[str] = []
        self.runners: list[RunnerResult] | None = None  # None until the runtime's start ends
        self.runner_error: tuple[str, ...] = ()
        self.session_error: tuple[str, tuple[str, ...]] | None = None
        self.results: list[ScenarioResult] = []
        self.closed = 0
        self.interrupted = False

    # Budget

    def _remaining(self, limit: float) -> float:
        return max(0.0, min(limit, self.deadline - asyncio.get_running_loop().time()))

    async def _bounded(self, start: Callable[[], Awaitable[Any]], limit: float) -> tuple[str, Any]:
        """``done``, ``timeout``, ``interrupted`` or ``budget``, and the result or the error.

        Nothing starts once a stop was asked or the budget is spent. The state is the one the
        wait ended in: an operation that returns after its deadline or a stop still reports
        that, and its late result comes back for the caller to close.
        """
        if self.stop.is_set():
            return "interrupted", None
        timeout = self._remaining(limit)
        if timeout <= 0:
            return "budget", None
        task = asyncio.ensure_future(start())
        waiter = asyncio.create_task(self.stop.wait())
        done: set[asyncio.Future[Any]] = set()
        try:
            done, _ = await asyncio.wait(
                (task, waiter), timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            waiter.cancel()
            if not task.done():
                task.cancel()
            # The operation's own cleanup finishes before this returns, even when cancelled.
            await wait_for_cleanup(
                asyncio.ensure_future(asyncio.gather(task, waiter, return_exceptions=True))
            )
        state = "done" if task in done else "interrupted" if self.stop.is_set() else "timeout"
        self.interrupted |= state == "interrupted"
        if task.cancelled():
            return state, None
        error = task.exception()
        return state, error if error is not None else task.result()

    # Steps

    async def execute(self) -> None:
        """The runtime started once, as start starts it, then each round of the scenario,
        each in a session of its own; nothing starts unauthorized, nor partly."""
        from alphaavatar.host.application.application import create_inference_runtime

        if self.blocked is not None:
            return
        config, tasks = self.config, self.plan.tasks
        runtime = create_inference_runtime(config)
        models = config.paths.cache.models_dir
        cached = await asyncio.to_thread(_cached_bytes, models)
        ended: list[int] = []

        async def start() -> None:
            try:
                await runtime.start()
            finally:
                ended.append(time.monotonic_ns())  # Ready, or failed: the start's own end.

        began = time.monotonic_ns()
        try:
            state, error = await self._bounded(start, self.limits.runners)
            if state == "budget":  # Nothing started: not a runner's failure.
                self.unstarted = "the diagnosis budget was spent before the runners started"
                self._unrun(tasks, "not run: budget exhausted", ())
                return
            grown = await asyncio.to_thread(_cached_bytes, models) - cached
            self.start = Metric(
                "runtime_start",
                round(((ended[0] if ended else time.monotonic_ns()) - began) / 1e6, 3),
                "ms",
                "runtime start began",
                "every runner ready, or the first failure",
                "inference runtime",
                note=_grown(grown),
            )
            started = state == "done" and error is None
            if state == "timeout":
                failure = (f"the runners did not start within {self.limits.runners:g} s",)
            else:
                failure = _diagnostic(error) if error is not None else ()
            self.runner_error = failure
            self.runners = [_runner(status, failure) for status in runtime.snapshot()]
            if not started:
                failed = next((r.method for r in self.runners if r.status == "FAIL"), None)
                stage = f"runner {failed} did not start" if failed else f"runners {state}"
                self._unrun(tasks, stage, failure, blocked_stage="runners")
                return
            for at in range(1, self.rounds + 1):
                for task in tasks:
                    if self.stop.is_set() or not self._remaining(self.limits.turn):
                        reason = "interrupted" if self.stop.is_set() else "budget exhausted"
                        self._unrun((task,), f"not run: {reason}", (), at=at)
                        continue
                    await self._session(task, at)
        finally:
            self.counters += runtime.snapshot()
            try:
                await runtime.close()
            except Exception as error:
                self.problems += _lines("inference runtime close", error)
            self.closed += 1

    async def _session(self, task: samples.Task, at: int) -> None:
        """One round of the scenario, in a session of its own: nothing of an earlier round
        is in its history."""
        from alphaavatar.host.application.bootstrap import create_execution
        from alphaavatar.host.execution.execution import HostExecution
        from alphaavatar.host.sessions.schemas import SessionContext

        config, tasks = self.config, (task,)
        session_id = f"doctor-{uuid4().hex}"
        access = SessionContext(
            device_id=_DEVICE,
            agent_device_id="doctor-avatar",
            room_name="doctor",
            metadata={"session_id": session_id, "session_type": self.plan.session_type},
        )
        began = time.monotonic_ns()
        state, built = await self._bounded(
            lambda: create_execution(config, access), self.limits.session
        )
        execution = built if isinstance(built, HostExecution) else None
        if state != "done" or execution is None:
            if execution is not None:  # Assembled after its deadline: closed, never used.
                await self._close("session", execution.aclose)
            reason = state if state != "done" else "assembly failed"
            details = _diagnostic(built) if isinstance(built, BaseException) else ()
            self._unrun(tasks, f"session {reason}", details, at=at)
            if self.session_error is None:
                self.session_error = (f"session {reason}", details)
            return
        runtime = execution.runtime
        sink = DiagnosticSink(runtime.output)
        timing = config.avatar.runtime.perception
        source = DiagnosticSource(
            runtime.perception,
            device_id=_DEVICE,
            frame_ms=timing.audio_frame_size_ms,
            video_interval_sec=timing.video_publish_interval_sec,
        )
        failed = None
        try:
            await sink.start()
            state, error = await self._bounded(execution.start, self.limits.session)
            if state != "done" or error is not None:
                details = _diagnostic(error) if error is not None else ()
                stage = f"session start {state if state != 'done' else 'failed'}"
                self._unrun(tasks, stage, details, at=at)
                if self.session_error is None:
                    self.session_error = (stage, details)
                return
            source.start(audio=True, screen=self.plan.vision)
            execution.engine.notify_ready()
            self.ready.append(round((time.monotonic_ns() - began) / 1e6, 3))
            failed = asyncio.create_task(execution.wait_failed(), name="doctor_session_failed")
            try:
                samples.speech(task.speech)
            except Exception as error:
                stage = f"fixed sample {task.speech} unavailable"
                self._unrun(tasks, stage, _diagnostic(error), at=at)
                return
            observation = await self._turn(execution, source, sink, task, failed, session_id, at)
            self.results.append(_measure(observation))
        finally:
            if failed is not None:
                failed.cancel()
                await asyncio.gather(failed, return_exceptions=True)
            source.stop()
            await self._close("output sink", sink.stop)
            await self._close("session", execution.aclose)
            self.closed += 1

    async def _close(self, label: str, close: Callable[[], Awaitable[None]]) -> None:
        try:
            await close()
        except Exception as error:
            self.problems += _lines(label, error)

    async def _turn(
        self,
        execution: Any,
        source: DiagnosticSource,
        sink: DiagnosticSink,
        task: samples.Task,
        failed: asyncio.Task[None],
        session_id: str,
        at: int = 1,
    ) -> TurnObservation:
        logs = self.logs
        trace = execution.runtime.perception.input_trace
        marks = len(sink.records), len(logs.records)
        done = asyncio.Event()
        ended = None
        deadline = asyncio.get_running_loop().time() + self._remaining(self.limits.turn)
        timeline = SourceTimeline()
        picture = samples.card_picture() if task.screen else None
        playing = asyncio.create_task(
            source.play(samples.speech(task.speech), picture, done, timeline), name="doctor_play"
        )
        turn_id = None
        try:
            while ended is None:
                if self.stop.is_set():
                    ended = "interrupted"
                elif failed.done():
                    ended = "session_failed"
                elif asyncio.get_running_loop().time() >= deadline:
                    ended = "timeout"
                if ended is not None:
                    break
                records = logs.records[marks[1] :]
                if turn_id is None:
                    turn_id = _find_turn(session_id, records, trace, timeline)
                if turn_id is not None and _finished(turn_id, records, sink.records[marks[0] :]):
                    break
                await asyncio.sleep(_POLL)
        finally:
            # The sample stops with the turn; one cut short leaves nothing playing.
            done.set()
            if ended is not None:
                playing.cancel()
            await asyncio.gather(playing, return_exceptions=True)
        if ended is not None and turn_id is not None:
            # What this turn still produces ends here; its session closes after it.
            try:
                await execution.runtime.output.interrupt(turn_id=turn_id, reason=TURN_ENDED)
            except Exception as error:
                self.problems += _lines("the unfinished turn's outputs", error)
        await asyncio.sleep(0.1)  # Trailing receipts and records of the same turn.
        self.interrupted |= ended == "interrupted"
        return TurnObservation(
            task=task,
            configuration=self.plan.configuration,
            session_id=session_id,
            start_ns=timeline.voiced_end_ns,
            timeline=timeline,
            turn_id=turn_id,
            records=sink.records[marks[0] :],
            logs=logs.records[marks[1] :],
            trace=trace.snapshot().to_dict()["records"],
            identity=trace.identity,
            ended=ended,
            dropped=sink.dropped,
            queues=dict(sink.queues),
            round=at,
        )

    def _unrun(
        self,
        tasks: Sequence[samples.Task],
        stage: str,
        details: tuple[str, ...],
        *,
        blocked_stage: str | None = None,
        at: int | None = None,
    ) -> None:
        """The scenario where it did not run: in round ``at``, or at all when the runtime did
        not start."""
        interrupted = "interrupted" in stage
        for task in tasks:
            self.results.append(
                ScenarioResult(
                    task.name,
                    ScenarioOutcome.INTERRUPTED
                    if interrupted
                    else ScenarioOutcome.CONDITIONS_UNMET,
                    f"Not run: {stage}",
                    self.plan.configuration,
                    blocked_stage=blocked_stage or stage,
                    details=details,
                    task=task.prompt,
                    round=at,
                )
            )

    # Report

    def checks(self) -> dict[str, Check]:
        from .doctor import _command, _dev

        doctor = _command("doctor", self.source)
        return {
            "session.start": self._start_check(doctor),
            "models.runners": self._runner_check(),
            "services.external": self._service_check(),
            "session.scenarios": self._scenario_check(),
            "session.cleanup": self._cleanup_check(_dev(self.source)),
        }

    def _start_check(self, doctor: str) -> Check:
        from .doctor import _dev

        if self.blocked is not None and self.plan.missing is not None:
            return Check(
                "session.start",
                CheckStatus.SKIP,
                f"Not run: Doctor has no scenario for this configuration: {self.plan.missing}",
                action="Turn voice on (voice.vad, voice.stt and voice.tts) for Doctor to "
                f"diagnose a session; `{_dev(self.source)}` tries this configuration as it is",
            )
        if self.blocked is not None:
            stores = unisolated(self.config)
            authorize = not self.config.host.doctor.external_services
            summary = (
                f"Not run: Doctor cannot isolate {', '.join(stores)} from real Avatar data"
                if stores
                else "Not run: the runtime diagnosis is not authorized, and "
                "host.doctor.external_services is false"
            )
            actions = []
            if authorize:
                actions.append(
                    "Run it at a terminal and agree, or allow it, model downloads and calls "
                    "that may be billed included: set host.doctor.external_services: true in "
                    f"the host profile, or run `{doctor} host.doctor.external_services=true`"
                )
            if stores:
                actions.append(
                    f"Doctor writes no remote vector store unless the configuration says it "
                    f"holds test data (host.doctor.test_stores: true); `{_dev(self.source)}` uses it"
                )
            return Check(
                "session.start",
                CheckStatus.SKIP,
                summary,
                (*self.names, *(f"not isolable: {store}" for store in stores)),
                "; ".join(actions),
            )
        rebound = tuple(f"moved into the temporary workspace: {item}" for item in self.rebound)
        if self.config.host.doctor.test_stores:
            # Written by the diagnosis, as the configuration allows: named, not hidden.
            rebound += tuple(
                f"a test store, as host.doctor.test_stores says: {store}"
                for store in remote_stores(self.config)
            )
        if self.unstarted is not None and not self.runners:
            return Check("session.start", CheckStatus.SKIP, f"Not run: {self.unstarted}", rebound)
        # No runner at all is a valid plan: the session's own start decides then.
        if self.runners is None or self.runner_error:
            return Check(
                "session.start",
                CheckStatus.FAIL,
                "Not run: the runners did not start; see models.runners",
                rebound,
                "Fix what models.runners names, then run doctor again",
            )
        if self.session_error is not None:
            stage, details = self.session_error
            return Check(
                "session.start",
                CheckStatus.FAIL,
                f"The diagnostic session did not start: {stage}",
                (*details, *rebound),
                "Fix the reported component, then run doctor again",
            )
        ready = sorted(self.ready)
        metrics = ()
        if ready:
            metrics = (
                Metric(
                    "session_ready",
                    round(statistics.median(ready), 3),
                    "ms",
                    "session assembly began",
                    "Engine ready",
                    "runtime, plugins and Engine of each diagnostic session, the median",
                    len(ready),
                    tuple(self.ready),
                ),
            )
        shown = f"{statistics.median(ready):.0f} ms" if ready else "unknown"
        count = f"{len(ready)} temporary sessions" if len(ready) > 1 else "A temporary session"
        return Check(
            "session.start",
            CheckStatus.PASS,
            f"{count} with the configured plugins, ready in {shown}"
            + (" at the median" if len(ready) > 1 else ""),
            rebound,
            metrics=metrics,
        )

    def _runner_check(self) -> Check:
        runners = self.runners or []
        every = tuple(self._served(runner) for runner in runners)
        starts = () if self.start is None else (self.start,)
        if not runners:
            if self.blocked is not None:
                reason = "the diagnosis did not start; see session.start"
            elif self.unstarted is not None:
                reason = self.unstarted
            elif self.runners is not None:
                reason = "no runner selected"
            else:
                reason = "not reached"
            return Check(
                "models.runners", CheckStatus.SKIP, f"Not started: {reason}", metrics=starts
            )
        failed = [runner for runner in runners if runner.status == CheckStatus.FAIL]
        pending = [runner for runner in runners if runner.status == CheckStatus.SKIP]
        error, start = self.runner_error, self.start
        began = (
            f"the runtime started in {start.value / 1000:.2f} s, {start.note}"
            if start is not None and start.value is not None
            else "the runtime started"
        )
        if not failed and not pending and not error:
            slowest = max(runners, key=lambda r: r.startup_seconds or 0.0)
            return Check(
                "models.runners",
                CheckStatus.PASS,
                f"{len(runners)} runners: {began}; slowest "
                f"{slowest.method} in {slowest.startup_seconds or 0:.2f} s",
                tuple(self._counted()),
                runners=every,
                metrics=(*starts, *self._queues()),
            )
        # Downloads are off only when this machine says so, for start as for Doctor.
        missing = model_not_cached(error)
        first = failed[0].method if failed else "a runner"
        action = (
            "Model downloads are switched off here (ALPHAAVATAR_MODEL_OFFLINE or HF_HUB_OFFLINE): "
            "unset them for start to download it, then run doctor again"
            if missing
            else "Fix what the error names (model file, package, device), then run doctor again"
        )
        return Check(
            "models.runners",
            CheckStatus.FAIL,
            f"{first} did not start{': its model is not in the cache' if missing else ''}; "
            f"{len(pending)} not reached",
            error,
            action,
            runners=every,
            metrics=starts,
        )

    def _summaries(self) -> dict[str, list[dict]]:
        """Each runner's summaries, by method, as its process logs them."""
        found: dict[str, list[dict]] = {}
        for record in self.logs.records if self.logs is not None else ():
            if record.name == "inference.summary":
                found.setdefault(record.fields.get("method"), []).append(record.fields)
        return found

    def _served(self, runner: RunnerResult) -> RunnerResult:
        """A runner with what it served, where its process summarized it."""
        summaries = self._summaries().get(runner.method)
        if not summaries:
            return runner
        return replace(
            runner,
            calls=sum(int(item.get("calls", 0)) for item in summaries),
            queue_wait_max_ms=round(max(float(i.get("queue_max_ms", 0.0)) for i in summaries), 3),
            execution_max_ms=round(
                max(float(i.get("execution_max_ms", 0.0)) for i in summaries), 3
            ),
        )

    def _queues(self) -> list[Metric]:
        """Each runner's queue wait and execution, as its process summarizes them."""
        found = self._summaries()
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

    def _service_check(self) -> Check:
        """Each external service: configured, authorized, reached by a stage, passed by it."""
        from .doctor import _dev

        authorized = self.config.host.doctor.external_services
        stores = unisolated(self.config)
        results = [self._service(name, kind, authorized, stores) for name, kind in self.services]
        rtc = (
            f"{self.config.host.rtc.backend} RTC server: not contacted; "
            f"`{_dev(self.source)}` connects to it"
        )
        details = (*map(_service_line, results), rtc)
        passed = sum(result.passed is True for result in results)
        failed = sum(result.passed is False for result in results)
        unverified = len(results) - passed - failed
        if not authorized and results:
            return Check(
                "services.external",
                CheckStatus.SKIP,
                "Not contacted: host.doctor.external_services is false",
                details,
                "The diagnostic session reaches them once host.doctor.external_services is "
                "true; calls may be billed",
                services=tuple(results),
            )
        summary = f"{passed} passed, {failed} failed, {unverified} not verified by the samples"
        status = CheckStatus.FAIL if failed else CheckStatus.PASS if passed else CheckStatus.SKIP
        return Check(
            "services.external",
            status,
            summary,
            details,
            "See the failed scenarios' blocked stages and causes" if failed else None,
            services=tuple(results),
        )

    def _service(
        self, name: str, kind: str, authorized: bool, stores: Sequence[str]
    ) -> ServiceResult:
        if not authorized:
            return ServiceResult(name, False, False, None, "not contacted: not authorized")
        if kind == "qdrant" and stores:
            return ServiceResult(name, True, False, None, "not contacted: real Avatar data")
        if kind in ("tools", "mcp", "custom"):
            note = "external access unknown" if kind == "custom" else "not exercised by the samples"
            return ServiceResult(name, True, None, None, note)
        measured = [
            r for r in self.results if r.outcome in (ScenarioOutcome.PASSED, ScenarioOutcome.FAILED)
        ]
        users = measured  # Every scenario speaks, and is answered in speech.
        if kind == "model" and not users and self.runners:
            # Vector stores probe their embedding provider as their runners start, after the
            # store opened: a start shows the probe answered, and only the probe's own error
            # is the provider's. A store that failed before it never reached the provider.
            embedding = embedding_runners(self.config)
            starts = {r.method: r.status for r in self.runners if r.method in embedding}
            failed = [method for method, status in starts.items() if status == CheckStatus.FAIL]
            if failed and probe_failed(self.runner_error):
                return ServiceResult(name, True, None, False, "the embedding probe failed")
            if failed:
                note = f"vector store embeddings: {failed[0]} failed before its probe"
                return ServiceResult(name, True, None, None, note)
            if starts and all(status == CheckStatus.PASS for status in starts.values()):
                return ServiceResult(name, True, True, True, "vector store embeddings")
            if starts:
                note = "vector store embeddings: an earlier runner did not start"
                return ServiceResult(name, True, None, None, note)
        if kind not in _SERVICE_STAGES or not users:
            return ServiceResult(name, True, None, None, "no stage that needs it ran")
        # Reached once it answered; passed when it served and no turn stopped at it.
        reach, serve, stops = _SERVICE_STAGES[kind]
        reached = True if any(reach in r.reached for r in users) else None
        broke = [
            r
            for r in users
            if r.blocked_stage in stops or (kind == "tts" and r.cause == "speech_synthesis_failed")
        ]
        served = any(serve in r.reached for r in users)
        passed = False if broke else True if served else None
        note = (broke[0].cause or f"stopped at {broke[0].blocked_stage}") if broke else None
        return ServiceResult(name, True, reached, passed, note)

    def _scenario_check(self) -> Check:
        results = list(self.results)
        names = {result.name for result in results}
        label = self.plan.configuration
        for task in self.plan.tasks:
            if task.name not in names:
                stage = (
                    self.blocked
                    if self.blocked is not None
                    else "the runners or the session did not start"
                )
                gate = "isolation" if unisolated(self.config) else "authorization"
                results.append(
                    ScenarioResult(
                        task.name,
                        ScenarioOutcome.CONDITIONS_UNMET,
                        f"Not run: {stage}",
                        label,
                        blocked_stage=gate if self.blocked is not None else "session.start",
                        task=task.prompt,
                    )
                )
        if self.plan.missing is not None:
            name = "voice_vision" if self.plan.vision else "voice"
            results.append(
                _absent(name, ScenarioOutcome.CONDITIONS_UNMET, self.plan.missing, label)
            )
        elif self.plan.vision:
            why = "vision is on: voice_vision speaks to it; voice runs with vision off"
            results.append(_absent("voice", ScenarioOutcome.NOT_ENABLED, why, label))
        else:
            why = "vision is off or text only: voice runs instead"
            results.append(_absent("voice_vision", ScenarioOutcome.NOT_ENABLED, why, label))
        results.append(
            _absent(
                "image_input",
                ScenarioOutcome.NO_COVERAGE,
                "no input transport delivers images to a session yet",
                label,
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
                label,
            )
        )
        failed = [r for r in results if r.outcome == ScenarioOutcome.FAILED]
        summaries = summarize(results)
        # Enabled, but not verified: what the configuration selects and no sample covered.
        uncovered = [
            r
            for r in results
            if r.outcome in (ScenarioOutcome.CONDITIONS_UNMET, ScenarioOutcome.INTERRUPTED)
            or (r.outcome == ScenarioOutcome.NO_COVERAGE and r.name == "visual_output")
        ]
        rounds = [f"{x.name} {x.passed}/{x.rounds} passed" for x in summaries]
        once = [r for r in results if r.round is None]
        count = {outcome: sum(r.outcome == outcome for r in once) for outcome in ScenarioOutcome}
        summary = ", ".join(
            [
                *rounds,
                *(f"{n} {outcome.value.replace('_', ' ')}" for outcome, n in count.items() if n),
            ]
        )
        if failed:
            status, action = (CheckStatus.FAIL, "See each failed round's stage, cause and evidence")
        elif any(r.outcome == ScenarioOutcome.PASSED for r in results):
            if uncovered:
                status, action = CheckStatus.WARN, "See what each scenario not run was missing"
                summary = (
                    f"Partial coverage: {', '.join(r.name for r in uncovered)} not verified; "
                    f"{summary}"
                )
            else:
                status, action = CheckStatus.PASS, None
        else:
            status = CheckStatus.SKIP
            action = None if self.blocked is None else "See session.start"
        return Check(
            "session.scenarios",
            status,
            summary,
            action=action,
            scenarios=tuple(results),
            summaries=summaries,
        )

    def _cleanup_check(self, dev: str) -> Check:
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


# By kind: the stage that shows a service answered, the one that shows it served, and the
# stages a turn stops at when it does not.
_SERVICE_STAGES = {
    "model": ("model.first_event", "text.complete", ("model.first_event", "text.first")),
    "stt": ("stt.final", "stt.final", ("stt.final",)),
    "tts": ("audio.first", "outputs.complete", ("audio.first",)),
}


def _find_turn(session_id: str, logs: list, trace: Any, timeline: SourceTimeline) -> str | None:
    """The Turn this input started: committed in this session, the range of perception
    events its cutoff closed holding the frame with the last voiced sample."""
    if timeline.voiced_end_sequence is None:
        return None
    committed = {
        record["turn_id"]: record
        for record in trace.snapshot().to_dict()["records"]
        if record["stage"] == "turn.committed" and "turn_id" in record
    }
    for record in logs:
        if record.name != "input.committed" or record.fields.get("session_id") != session_id:
            continue
        turn_id = record.fields.get("turn_id")
        cut = committed.get(trace.identity(turn_id)) if turn_id else None
        if cut is None:
            continue
        start, end = cut.get("start_cutoff_sequence", 0), cut.get("cutoff_sequence", 0)
        if start < timeline.voiced_end_sequence <= end:
            return turn_id
    return None


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


def _service_line(result: ServiceResult) -> str:
    def state(value: bool | None, yes: str, no: str) -> str:
        return yes if value else no if value is False else f"{yes}: not observed"

    parts = [
        "authorized" if result.authorized else "not authorized",
        state(result.reached, "reached", "not reached"),
        state(result.passed, "passed", "failed"),
    ]
    note = f" ({result.note})" if result.note else ""
    return f"{result.name}: configured, {', '.join(parts)}{note}"


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


def _absent(name: str, outcome: ScenarioOutcome, reason: str, label: str) -> ScenarioResult:
    return ScenarioResult(name, outcome, reason[0].upper() + reason[1:], label)


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
