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
inside it (``isolate``). Each configuration tried, the original and any degradation, plans and
starts its own runners in an InferenceRuntime and its sessions from ``create_execution``; only
the transport is Doctor's (``transport``). External services, often billed, are reached only
with ``host.doctor.external_services``; real Avatar data Doctor cannot isolate, a remote
vector store, is never written, so what needs it is skipped: the two are separate bounds.
Each step starts only inside the remaining budget and keeps the state its wait ended in;
whatever was started is closed in reverse after success, failure, timeout or interruption,
and what closing could not reclaim is reported.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from alphaavatar.core.cleanup import wait_for_cleanup

from . import samples
from .enums import CheckStatus, ScenarioOutcome
from .measure import TURN_ENDED, TurnObservation, scenario
from .schemas import Check, Metric, RunnerResult, ScenarioResult, ServiceResult
from .transport import DiagnosticSink, DiagnosticSource, LogTimings, SourceTimeline

if TYPE_CHECKING:
    from alphaavatar.host.configs import ApplicationConfig, ConfigSource

SESSION_SECONDS = 180.0  # Runners from the cache, or a session's plugins and readiness
TURN_SECONDS = 60.0  # One scenario turn, from its first input to its outputs' end
TOTAL_SECONDS = 480.0  # Everything, closing excluded: each close has its own bounds
_DEVICE = "doctor-participant"
_POLL = 0.02


@dataclass(frozen=True, slots=True)
class Budget:
    session: float
    turn: float
    total: float


def budget() -> Budget:
    return Budget(SESSION_SECONDS, TURN_SECONDS, TOTAL_SECONDS)


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
    """The default plugins' vector stores: capability, its section, its store settings."""
    avatar = config.avatar
    found = [("memory", "memory", avatar.memory), ("persona", "persona", avatar.persona)]
    if avatar.tools.mcp.enabled:
        found.append(("mcp", "tools.mcp", avatar.tools.mcp))
    return [(name, key, part.vdb_config) for name, key, part in found if part.plugin == "default"]


def unisolated(config: ApplicationConfig) -> list[str]:
    """Real Avatar data Doctor cannot keep apart from its own: remote vector stores."""
    from alphaavatar.agents.utils.vdb.config import vdb_backend

    return [
        f"{name}'s Qdrant store" for name, _, vdb in _stores(config) if vdb_backend(vdb) == "qdrant"
    ]


def isolate(config: ApplicationConfig, workspace: str) -> tuple[ApplicationConfig, tuple[str, ...]]:
    """The snapshot on Doctor's storage: ``workspace`` as the Avatar workspace, and each
    explicit local vector store path moved inside it, where the default would be."""
    from alphaavatar.agents.utils.vdb.config import vdb_backend
    from alphaavatar.core.workspace import WorkspacePaths

    changes: dict[str, object] = {"avatar.workspace_root": workspace}
    rebound = []
    indexes = WorkspacePaths.from_root(workspace).data.indexes
    for name, key, vdb in _stores(config):
        if vdb_backend(vdb) == "lancedb" and vdb.get("client_path"):
            path = indexes.namespace(name).backend("lancedb").root
            changes[f"{key}.vdb_config.client_path"] = str(path)
            rebound.append(f"{name}'s LanceDB path")
    return derive(config, changes), tuple(rebound)


def vision_off(config: ApplicationConfig) -> ApplicationConfig:
    """A camera-less device: vision off, and the default plugins' camera consumers with it."""
    avatar = config.avatar
    changes: dict[str, object] = {"vision.enabled": False}
    if avatar.persona.plugin == "default":
        changes["persona.init_config.face.enabled"] = False
    if avatar.router.plugin == "default":
        changes["router.init_config.addressing.visual.enabled"] = False
    return derive(config, changes)


# What may start


def start_services(config: ApplicationConfig) -> list[str]:
    """What starting the runners reaches, or cannot be shown not to: vector stores embed a
    probe text, and a runner Doctor does not ship may do anything."""
    from alphaavatar.agents.runtime.inference import plan_inference_runners

    avatar, found = config.avatar, []
    for name in ("memory", "persona"):
        if getattr(avatar, name).plugin == "default":
            found.append(f"{name} vector store embeddings")
    mcp = avatar.tools.mcp
    if mcp.enabled and mcp.plugin == "default" and mcp.servers:
        found.append("mcp tool index embeddings")
    custom = sorted(
        method
        for method, runner in plan_inference_runners(avatar).items()
        if not runner.__module__.startswith("alphaavatar.plugins.")
    )
    if custom:
        found.append(f"custom runners ({', '.join(custom)}), external access unknown")
    return found


def blocked(config: ApplicationConfig, services: Sequence[str]) -> str | None:
    """Why the session may not start: data it cannot isolate, services it may not reach."""
    reasons = []
    if stores := unisolated(config):
        reasons.append(f"real Avatar data cannot be isolated: {', '.join(stores)}")
    if services and not config.host.doctor.external_services:
        reasons.append(f"not authorized: {', '.join(services)}")
    return "; ".join(reasons) or None


def starts(config: ApplicationConfig, services: Sequence[str]) -> bool:
    """Whether the session step starts anything: the session itself when it may, or else the
    runners alone, when starting them reaches nothing beyond this machine."""
    from alphaavatar.agents.runtime.inference import plan_inference_runners

    if blocked(config, services) is None:
        return True
    return not start_services(config) and bool(plan_inference_runners(config.avatar))


def unstarted(
    config: ApplicationConfig, source: ConfigSource, services: Sequence[tuple[str, str]]
) -> dict[str, Check]:
    """The session's checks when it starts nothing: why, and what would allow it."""
    run = _Run(config, source, services, asyncio.Event(), budget())
    if found := start_services(config):
        run.unstarted = f"starting them reaches {', '.join(found)}, which needs authorization"
    else:
        run.unstarted = "no runner selected"
    return run.checks()


async def diagnose_session(
    config: ApplicationConfig,
    source: ConfigSource,
    services: Sequence[tuple[str, str]],
    rebound: Sequence[str],
    *,
    limits: Budget,
    stop: asyncio.Event,
    logs: LogTimings,
) -> dict[str, Check]:
    """The session's checks, ``services.external`` with them, from the isolated snapshot.

    Runs in the diagnostic process; ``services`` names and kinds the external services the
    configuration reaches, as ``doctor`` lists them.
    """
    run = _Run(config, source, services, stop, limits, logs)
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
    ) -> None:
        self.config, self.source, self.stop, self.limits = config, source, stop, limits
        self.services = tuple(services)
        self.names = [name for name, _ in self.services]
        self.blocked = blocked(config, self.names)
        self.plan = plan(config)
        self.logs = logs
        self.deadline = 0.0  # Set when the session step runs, on its event loop's clock.
        self.unstarted: str | None = None  # Why no runner starts, when that is decided first
        self.rebound: tuple[str, ...] = ()  # Local stores moved into the temporary workspace
        self.counters: list[Any] = []  # Each runtime's own counters, before it closed
        self.problems: list[str] = []
        self.runners: dict[str, list[RunnerResult]] = {}  # By configuration tried
        self.runner_error: dict[str, tuple[str, ...]] = {}
        self.session: Metric | None = None  # Readiness of the original configuration's session
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
        from alphaavatar.agents.runtime.inference import plan_inference_runners

        config = self.config
        if self.blocked is not None:
            # Only runners that reach nothing beyond this machine, and only for their start.
            if not start_services(config) and plan_inference_runners(config.avatar):
                await self._attempt(config, "original", (), "chat")
            return
        await self._attempt(config, "original", self.plan.tasks, self.plan.session_type)
        for configuration, derived, session_type, tasks in self._degradations():
            if self.stop.is_set() or not self._remaining(self.limits.session):
                reason = "interrupted" if self.stop.is_set() else "budget exhausted"
                self._unrun(tasks, configuration, f"not run: {reason}", ())
                continue
            await self._attempt(derived, configuration, tasks, session_type)

    async def _attempt(
        self,
        config: ApplicationConfig,
        configuration: str,
        tasks: Sequence[samples.Task],
        session_type: str,
    ) -> None:
        """One configuration: its own runners, then sessions until its turns are done."""
        from alphaavatar.agents.runtime.inference import (
            InferenceRuntime,
            RunnerLaunch,
            plan_inference_runners,
            snapshot_inference_config,
        )

        runtime = InferenceRuntime(
            plan_inference_runners(config.avatar),
            mp_ctx=mp.get_context("spawn"),
            launch=RunnerLaunch(
                str(config.workspace.root),
                str(config.paths.cache.models_dir),
                config=snapshot_inference_config(config.avatar),
            ),
            config=config.avatar.runtime.inference,
        )
        try:
            state, error = await self._bounded(runtime.start, self.limits.session)
            if state == "budget":  # Nothing started: not a runner's failure.
                if configuration == "original":
                    self.unstarted = "the diagnosis budget was spent before the runners started"
                self._unrun(tasks, configuration, "not run: budget exhausted", ())
                return
            started = state == "done" and error is None
            if state == "timeout":
                failure = (f"the runners did not start within {self.limits.session:g} s",)
            else:
                failure = _diagnostic(error) if error is not None else ()
            self.runner_error[configuration] = failure
            self.runners[configuration] = [
                _runner(status, failure, configuration) for status in runtime.snapshot()
            ]
            if not started:
                failed = next(
                    (r.method for r in self.runners[configuration] if r.status == "FAIL"), None
                )
                stage = f"runner {failed} did not start" if failed else f"runners {state}"
                self._unrun(tasks, configuration, stage, failure, blocked_stage="runners")
                return
            remaining = list(tasks)
            while remaining:
                if self.stop.is_set() or not self._remaining(self.limits.turn):
                    reason = "interrupted" if self.stop.is_set() else "budget exhausted"
                    self._unrun(remaining, configuration, f"not run: {reason}", ())
                    break
                remaining = await self._session(config, configuration, session_type, remaining)
        finally:
            self.counters += runtime.snapshot()
            try:
                await runtime.close()
            except Exception as error:
                self.problems += _lines(f"inference runtime ({configuration}) close", error)
            self.closed += 1

    async def _session(
        self,
        config: ApplicationConfig,
        configuration: str,
        session_type: str,
        tasks: Sequence[samples.Task],
    ) -> list[samples.Task]:
        """Turns in one session; after a turn that did not end on its own, the rest are left
        for a fresh session, so nothing of that turn reaches the next one."""
        from alphaavatar.host.application.bootstrap import create_execution
        from alphaavatar.host.execution.execution import HostExecution
        from alphaavatar.host.sessions.schemas import SessionContext

        session_id = f"doctor-{uuid4().hex}"
        access = SessionContext(
            device_id=_DEVICE,
            agent_device_id="doctor-avatar",
            room_name="doctor",
            metadata={"session_id": session_id, "session_type": session_type},
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
            self._unrun(tasks, configuration, f"session {reason}", details)
            if configuration == "original" and self.session_error is None:
                self.session_error = (f"session {reason}", details)
            return []
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
                self._unrun(tasks, configuration, stage, details)
                if configuration == "original" and self.session_error is None:
                    self.session_error = (stage, details)
                return []
            source.start(audio=session_type != "chat", screen=session_type == "video")
            execution.engine.notify_ready()
            if configuration == "original" and self.session is None:
                self.session = Metric(
                    "session_ready",
                    round((time.monotonic_ns() - began) / 1e6, 3),
                    "ms",
                    "session assembly began",
                    "Engine ready",
                    "runtime, plugins and Engine of the diagnostic session",
                )
            failed = asyncio.create_task(execution.wait_failed(), name="doctor_session_failed")
            for index, task in enumerate(tasks):
                if self.stop.is_set() or not self._remaining(self.limits.turn):
                    reason = "interrupted" if self.stop.is_set() else "budget exhausted"
                    self._unrun(tasks[index:], configuration, f"not run: {reason}", ())
                    return []
                if task.speech is not None:
                    try:
                        samples.speech(task.speech)
                    except Exception as error:
                        stage = f"fixed sample {task.speech} unavailable"
                        self._unrun((task,), configuration, stage, _diagnostic(error))
                        continue
                observation = await self._turn(
                    execution, source, sink, task, configuration, failed, session_id
                )
                self.results.append(_measure(observation))
                if observation.ended is not None:
                    return list(tasks[index + 1 :])
            return []
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
        configuration: str,
        failed: asyncio.Task[None],
        session_id: str,
    ) -> TurnObservation:
        logs = self.logs
        perception = execution.runtime.perception
        trace = perception.input_trace
        marks = len(sink.records), len(logs.records)
        first = perception.latest_event_sequence  # Later events are this turn's input.
        done = asyncio.Event()
        timeline, playing, start_ns, ended = None, None, None, None
        deadline = asyncio.get_running_loop().time() + self._remaining(self.limits.turn)
        if task.speech is not None:
            timeline = SourceTimeline()
            picture = samples.card_picture() if task.screen else None
            playing = asyncio.create_task(
                source.play(samples.speech(task.speech), picture, done, timeline),
                name="doctor_play",
            )
        else:
            state, accepted = await self._bounded(
                lambda: source.type(execution.engine, task.text), self.limits.turn
            )
            start_ns = accepted if state == "done" and isinstance(accepted, int) else None
            ended = None if state == "done" else _ENDED.get(state, "timeout")
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
                    turn_id = _find_turn(task, session_id, records, trace, first, timeline)
                if turn_id is not None and _finished(turn_id, records, sink.records[marks[0] :]):
                    break
                await asyncio.sleep(_POLL)
        finally:
            # The sample stops with the turn; one cut short leaves nothing playing.
            done.set()
            if playing is not None:
                if ended is not None:
                    playing.cancel()
                await asyncio.gather(playing, return_exceptions=True)
        if timeline is not None:
            start_ns = timeline.voiced_end_ns
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
            configuration=configuration,
            session_id=session_id,
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

    def _degradations(self) -> list[tuple[str, ApplicationConfig, str, tuple[samples.Task, ...]]]:
        """The existing fallbacks the original's own cause calls for, each tried on its own
        configuration: vision unavailable, then speech output unavailable."""
        original = [r for r in self.results if r.configuration == "original"]
        found = {r.name: r for r in original}
        trials = []
        if self.plan.vision and self._vision_unavailable(found.get("voice_vision")):
            # Nothing ran when the original could not start: the typed turn goes along.
            ran = "text" in found and found["text"].blocked_stage != "runners"
            tasks = (samples.VOICE,) if ran else (samples.VOICE, samples.TEXT)
            config = vision_off(self.config)
            trials.append(("degraded: vision off", config, "audio", tasks))
        spoken = [r for r in original if r.name in ("voice", "voice_vision", "text")]
        if self.plan.audio_output and any(_speech_failed(r) for r in spoken):
            trials.append(("degraded: text output", self.config, "chat", (samples.TEXT,)))
        return trials

    def _vision_unavailable(self, result: ScenarioResult | None) -> bool:
        """The model refused the pictures, or a runner only vision needs could not start."""
        from alphaavatar.agents.runtime.inference import plan_inference_runners

        if result is not None and result.cause == "ModelCapabilityError":
            return True
        failed = {r.method for r in self.runners.get("original", ()) if r.status == "FAIL"}
        if not failed:
            return False
        without = plan_inference_runners(vision_off(self.config).avatar)
        return bool(failed - set(without))

    def _unrun(
        self,
        tasks: Sequence[samples.Task],
        configuration: str,
        stage: str,
        details: tuple[str, ...],
        *,
        blocked_stage: str | None = None,
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
                    blocked_stage=blocked_stage or stage,
                    details=details,
                    task=task.prompt,
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

        if self.blocked is not None:
            stores = unisolated(self.config)
            authorize = bool(self.names) and not self.config.host.doctor.external_services
            summary = (
                "Not run: the session would reach external services, and "
                "host.doctor.external_services is false"
                if authorize
                else f"Not run: Doctor cannot isolate {', '.join(stores)} from real Avatar data"
            )
            actions = []
            if authorize:
                actions.append(
                    "To allow these calls, which may be billed: set "
                    "host.doctor.external_services: true in the host profile, or run "
                    f"`{doctor} host.doctor.external_services=true`"
                )
            if stores:
                actions.append(
                    f"Doctor never writes to a remote vector store; `{_dev(self.source)}` uses it"
                )
            return Check(
                "session.start",
                CheckStatus.SKIP,
                summary,
                (*self.names, *(f"not isolable: {store}" for store in stores)),
                "; ".join(actions),
            )
        rebound = tuple(f"moved into the temporary workspace: {item}" for item in self.rebound)
        if self.unstarted is not None and not self.runners.get("original"):
            return Check("session.start", CheckStatus.SKIP, f"Not run: {self.unstarted}", rebound)
        if not self.runners.get("original") or self.runner_error.get("original"):
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
        metrics = (self.session,) if self.session is not None else ()
        ready = f"{self.session.value:.0f} ms" if self.session is not None else "unknown"
        return Check(
            "session.start",
            CheckStatus.PASS,
            f"A temporary session with the configured plugins was ready in {ready}",
            rebound,
            metrics=metrics,
        )

    def _runner_check(self) -> Check:
        from alphaavatar.agents.utils.files.model.model_files import models_offline

        from .doctor import _dev

        runners = self.runners.get("original", [])
        # Each degradation started its own: shown apart, the original's result stands.
        degraded = [(c, found) for c, found in self.runners.items() if c != "original"]
        others = [
            f"{configuration}: " + ", ".join(f"{r.method} {r.summary}" for r in found)
            for configuration, found in degraded
        ]
        every = (*runners, *(runner for _, found in degraded for runner in found))
        if not runners:
            if self.unstarted is not None:
                reason = self.unstarted
            elif "original" in self.runners:
                reason = "no runner selected"
            else:
                reason = "not reached"
            return Check("models.runners", CheckStatus.SKIP, f"Not started: {reason}")
        failed = [runner for runner in runners if runner.status == CheckStatus.FAIL]
        pending = [runner for runner in runners if runner.status == CheckStatus.SKIP]
        error = self.runner_error.get("original", ())
        if not failed and not pending and not error:
            slowest = max(runners, key=lambda r: r.startup_seconds or 0.0)
            return Check(
                "models.runners",
                CheckStatus.PASS,
                f"{len(runners)} runners started from the cache, offline; slowest "
                f"{slowest.method} in {slowest.startup_seconds or 0:.2f} s",
                (*self._counted(), *others),
                runners=every,
                metrics=tuple(self._queues()),
            )
        missing = any("FileNotFoundError" in line for line in error)
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
            (*error, *others),
            action,
            runners=every,
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
        spoken = ("voice", "voice_vision")
        users = [r for r in measured if kind != "stt" or r.name in spoken]
        if kind == "tts":
            users = [r for r in users if r.configuration != "degraded: text output"]
        if kind == "model" and not users and self.runners.get("original"):
            started = not self.runner_error.get("original")
            embeds = any("embeddings" in item for item in start_services(self.config))
            if embeds:
                return ServiceResult(name, True, started, started, "vector store embeddings")
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
                        "original",
                        blocked_stage=gate if self.blocked is not None else "session.start",
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
        # Enabled, but not verified: what the configuration selects and no sample covered.
        uncovered = [
            r
            for r in original
            if r.outcome in (ScenarioOutcome.CONDITIONS_UNMET, ScenarioOutcome.INTERRUPTED)
            or (r.outcome == ScenarioOutcome.NO_COVERAGE and r.name == "visual_output")
        ]
        count = {outcome: sum(r.outcome == outcome for r in results) for outcome in ScenarioOutcome}
        summary = ", ".join(
            f"{n} {outcome.value.replace('_', ' ')}" for outcome, n in count.items() if n
        )
        if degraded:
            summary += f"; degraded: {', '.join(f'{r.name} {r.outcome.value}' for r in degraded)}"
        if failed:
            status, action = (
                CheckStatus.FAIL,
                "See each failed scenario's blocked stage, cause and evidence",
            )
        elif any(r.outcome == ScenarioOutcome.PASSED for r in original):
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
        return Check("session.scenarios", status, summary, action=action, scenarios=tuple(results))

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
            f"{self.closed} owned parts closed: sessions and executor before each runtime; "
            "runner processes, sockets and the temporary workspace reclaimed",
        )


_ENDED = {"interrupted": "interrupted", "timeout": "timeout", "budget": "timeout"}
# By kind: the stage that shows a service answered, the one that shows it served, and the
# stages a turn stops at when it does not.
_SERVICE_STAGES = {
    "model": ("model.first_event", "text.complete", ("model.first_event", "text.first")),
    "stt": ("stt.final", "stt.final", ("stt.final",)),
    "tts": ("audio.first", "outputs.complete", ("audio.first",)),
}


def _find_turn(
    task: samples.Task,
    session_id: str,
    logs: list,
    trace: Any,
    first: int,
    timeline: SourceTimeline | None,
) -> str | None:
    """The Turn this input started: committed in this session, its cutoff over this input.

    A spoken turn's range of perception events holds the frame with the last voiced sample;
    a typed one commits this text after the turn began.
    """
    if task.speech is not None and (timeline is None or timeline.voiced_end_sequence is None):
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
        if task.speech is not None:
            if start < timeline.voiced_end_sequence <= end:
                return turn_id
        elif record.text == task.text and end > first:
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


def _speech_failed(result: ScenarioResult) -> bool:
    """The answer was there, its speech was not: no audio, or audio cut short by failure."""
    if result.outcome != ScenarioOutcome.FAILED:
        return False
    return result.blocked_stage == "audio.first" or any(
        "audio" in (item.get("modalities") or "") and item.get("terminal") == "failed"
        for item in result.outputs
    )


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


def _absent(name: str, outcome: ScenarioOutcome, reason: str) -> ScenarioResult:
    return ScenarioResult(name, outcome, reason[0].upper() + reason[1:], "original")


def _runner(status: Any, error: tuple[str, ...], configuration: str) -> RunnerResult:
    if status.startup_state == "ready":
        return RunnerResult(
            status.method,
            CheckStatus.PASS,
            "started",
            startup_seconds=status.startup_elapsed_seconds,
            configuration=configuration,
        )
    if status.startup_state in ("failed", "cancelled"):
        return RunnerResult(
            status.method,
            CheckStatus.FAIL,
            f"{status.startup_state}: {status.error_type}",
            error,
            status.startup_elapsed_seconds,
            configuration,
        )
    return RunnerResult(
        status.method,
        CheckStatus.SKIP,
        "not reached: an earlier runner did not start",
        configuration=configuration,
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
