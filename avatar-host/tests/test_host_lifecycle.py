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
"""Host and execution bootstrap release shared inference only after its borrowers settle."""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from unittest import mock

import pytest
from inference_runner_samples import JournalRunner

import alphaavatar.plugins.context  # noqa: F401  Registers the real plugin this test substitutes.
import alphaavatar.plugins.loop  # noqa: F401  Registers the real plugin this test substitutes.
from alphaavatar.agents.avatar.context import ContextManager
from alphaavatar.agents.avatar.loop import Loop
from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.configs.runtime_config import InferenceConfig
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import (
    INFERENCE_ENDPOINT_ENV,
    InferenceRuntime,
    RunnerLaunch,
)
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.workspace import WorkspacePaths
from alphaavatar.host.application.application import AvatarHost
from alphaavatar.host.application.bootstrap import create_avatar_runtime
from alphaavatar.host.configs.loader import validate_application
from alphaavatar.host.processes.supervisor import ProcessSupervisor
from alphaavatar.host.sessions.schemas import SessionRequest

HANG_GUARD = 60
JOURNAL = JournalRunner.INFERENCE_METHOD

# Replaces only the LiveKit-bound session body inside a real execution child process.
CHILD_SITE = f"""
import os

import alphaavatar.host.application.bootstrap as bootstrap


async def run_execution(config, request, *, stop, ready):
    from alphaavatar.agents.runtime.inference import InferenceExecutor

    executor = InferenceExecutor.from_env(config.avatar.runtime.inference)
    try:
        await ready()
        await stop.wait()
        final = f"final:{{os.getpid()}}".encode()
        result = await executor.do_inference({JOURNAL!r}, final)
    finally:
        await executor.close()
    return "final_inference_ok" if result == final else "final_inference_mismatch"


bootstrap.run_execution = run_execution
"""


class Probe:
    def __init__(
        self, runtime: AvatarRuntime, events: list[str], *, failure: BaseException | None = None
    ) -> None:
        self.runtime, self.events, self.failure = runtime, events, failure

    async def aclose(self) -> None:
        # Rollback must still let consumers settle against the shared inference service.
        result = await self.runtime.inference.do_inference(JOURNAL, type(self).__name__.encode())
        self.events.append(f"{type(self).__name__}:{result.decode()}")
        if self.failure is not None:
            raise self.failure


class ProbeLoop(Probe, Loop):
    def __init__(self, runtime: AvatarRuntime, events: list[str], *, blocked: bool = False):
        super().__init__(runtime, events)
        self.blocked, self.started = blocked, asyncio.Event()

    @property
    def ready(self) -> bool:
        return False

    async def initialize(self) -> None:
        self.started.set()
        if self.blocked:
            await asyncio.Event().wait()
        raise RuntimeError("loop initialization failed")

    async def submit(self, request, *, authorize=None):
        raise NotImplementedError

    def interrupt(self, *, run_id: str | None = None, reason: str = "interrupted") -> None:
        pass


class ProbeContext(Probe, ContextManager):
    @property
    def initial_instructions(self) -> str:
        return ""

    def bind_sources(self, *, memory, persona) -> None:
        raise NotImplementedError

    def accept_turn(self, snapshot):
        raise NotImplementedError

    async def prepare(self, request):
        raise NotImplementedError

    def build(self, prefix, *, continuation=()):
        raise NotImplementedError


class ProbePlugin(AvatarModulePlugin):
    def __init__(self, create: Callable[..., Probe]) -> None:
        super().__init__("probe", "0", "tests")
        self.create, self.created = create, []

    def get_plugin(self, *, runtime: AvatarRuntime, **_: object) -> Probe:
        self.created.append(self.create(runtime))
        return self.created[-1]


class RecordingInference(InferenceRuntime):
    """Record the Host's reclamation facts at the moment it releases the shared service."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.observe: Callable[[], object] = lambda: None
        self.observed: list[object] = []

    async def close(self) -> None:
        self.observed.append(self.observe())
        await super().close()


@asynccontextmanager
async def shared_inference(
    root: Path, owned_endpoints: set[object]
) -> AsyncIterator[RecordingInference]:
    service = RecordingInference(
        {JOURNAL: JournalRunner},
        mp_ctx=mp.get_context("spawn"),
        launch=RunnerLaunch(
            str(root), str(root / "models"), config=json.dumps({"test": {"root": str(root)}})
        ),
        config=InferenceConfig(initialize_timeout=HANG_GUARD, close_timeout=1),
    )
    try:
        async with asyncio.timeout(HANG_GUARD):
            await service.start()
        owned_endpoints.add(service.endpoint)
        yield service
    finally:
        await service.close()


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.01)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


def journal(root: Path) -> list[str]:
    path = root / f"{JOURNAL}.journal"
    return (
        [line.split(" ", 1)[1] for line in path.read_text().splitlines()] if path.exists() else []
    )


def host(tmp_path: Path) -> AvatarHost:
    config = validate_application(
        {
            "application": {"home": str(tmp_path / "application")},
            "avatar": {"id": "host-lifecycle"},
            "host": {
                "processes": {"capacity": 1, "shutdown_timeout": 30.0, "ipc_timeout": 10.0},
                "health": {"bind": "127.0.0.1"},
            },
        }
    )
    # Credentials are read at construction only; the backend never serves in these tests.
    credentials = {"LIVEKIT_URL": "wss://livekit.invalid", "LIVEKIT_API_KEY": "k"}
    with mock.patch.dict(os.environ, {**credentials, "LIVEKIT_API_SECRET": "s"}):
        return AvatarHost(config, devmode=True)


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize("cleanup_failure", [None, OSError("context cleanup failed")])
async def test_bootstrap_rollback_releases_every_resource_after_loop_initialization_fails(
    tmp_path: Path,
    socket_root: Path,
    owned_endpoints: set[object],
    monkeypatch: pytest.MonkeyPatch,
    cleanup_failure: BaseException | None,
) -> None:
    events: list[str] = []
    loops = ProbePlugin(lambda runtime: ProbeLoop(runtime, events))
    contexts = ProbePlugin(lambda runtime: ProbeContext(runtime, events, failure=cleanup_failure))
    monkeypatch.setitem(AvatarModulePlugin._registry[AvatarModule.LOOP], "realtime", loops)
    monkeypatch.setitem(AvatarModulePlugin._registry[AvatarModule.CONTEXT], "default", contexts)
    session = SessionRuntime(session_id="bootstrap")
    workspace = WorkspacePaths.from_root(tmp_path / "workspace")

    async with shared_inference(tmp_path, owned_endpoints) as service:
        with pytest.raises(RuntimeError, match="loop initialization failed") as failed:
            async with asyncio.timeout(HANG_GUARD):
                await create_avatar_runtime(
                    avatar_config=AvatarConfig.model_validate({"avatar": {"id": "bootstrap"}}),
                    workspace=workspace,
                    session=session,
                    session_path=workspace.data.sessions.get("bootstrap", date(2026, 11, 2)),
                    state=StateRuntime(),
                )
        if cleanup_failure is not None:
            # The original failure wins; the rollback failure stays attached, not lost.
            cause = pytest.ExceptionInfo.from_exception(failed.value.__cause__)
            assert cause.group_contains(OSError, match="context cleanup failed")
        assert events == ["ProbeLoop:ProbeLoop", "ProbeContext:ProbeContext"]
        runtime = loops.created[0].runtime
        with pytest.raises(RuntimeError, match="Inference executor is closed"):
            await runtime.inference.do_inference(JOURNAL, b"late")
        with pytest.raises(RuntimeError, match="OutputRuntime is closed"):
            await runtime.output.start_turn(turn_id="late")
        assert service.is_alive and not workspace.root.exists()


async def test_cancelled_bootstrap_rolls_back_before_cancellation_propagates(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    loops = ProbePlugin(lambda runtime: ProbeLoop(runtime, events, blocked=True))
    contexts = ProbePlugin(lambda runtime: ProbeContext(runtime, events))
    monkeypatch.setitem(AvatarModulePlugin._registry[AvatarModule.LOOP], "realtime", loops)
    monkeypatch.setitem(AvatarModulePlugin._registry[AvatarModule.CONTEXT], "default", contexts)
    session = SessionRuntime(session_id="bootstrap")
    workspace = WorkspacePaths.from_root(tmp_path / "workspace")

    async with shared_inference(tmp_path, owned_endpoints) as service:
        bootstrap = asyncio.create_task(
            create_avatar_runtime(
                avatar_config=AvatarConfig.model_validate({"avatar": {"id": "bootstrap"}}),
                workspace=workspace,
                session=session,
                session_path=workspace.data.sessions.get("bootstrap", date(2026, 11, 2)),
                state=StateRuntime(),
            )
        )
        await wait_until(lambda: bool(loops.created), "the Loop was never created")
        await loops.created[0].started.wait()
        bootstrap.cancel()
        async with asyncio.timeout(HANG_GUARD):
            with pytest.raises(asyncio.CancelledError):
                await bootstrap
        assert events == ["ProbeLoop:ProbeLoop", "ProbeContext:ProbeContext"]
        with pytest.raises(RuntimeError, match="Inference executor is closed"):
            await loops.created[0].runtime.inference.do_inference(JOURNAL, b"late")
        assert service.is_alive


async def test_host_reaps_execution_children_before_releasing_shared_inference(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object]
) -> None:
    site = tmp_path / "child-site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(CHILD_SITE)
    avatar_host = host(tmp_path)
    manager = avatar_host._manager

    async with shared_inference(tmp_path, owned_endpoints) as service:
        avatar_host._inference = (
            service  # Real shared service; its model bootstrap is not under test.
        )
        reservation = manager.reserve(backend="livekit", source_id="session")
        assert reservation is not None
        request = SessionRequest(
            attachment_id=reservation.attachment_id,
            backend="livekit",
            source_id="session",
            connection={},
        )
        # The child inherits the session-body replacement only while it is being spawned.
        with mock.patch.dict(os.environ, {"PYTHONPATH": str(site)}):
            assert manager.assign(reservation, request)
            await wait_until(
                lambda: [view.state for view in manager.snapshot()] == ["running"],
                "the execution child never became ready",
            )
        (child,) = manager.snapshot()
        assert child.pid is not None and pid_exists(child.pid)
        service.observe = lambda: (avatar_host._supervisor.all_reaped, pid_exists(child.pid))

        async with asyncio.timeout(HANG_GUARD):
            await avatar_host.aclose()

        # The child finished its shutdown-time inference, was reaped, then inference closed.
        assert service.observed == [(True, False)]
        (settled,) = manager.snapshot()
        assert (settled.state, settled.reason, settled.stop_reason) == (
            "success",
            "final_inference_ok",
            "host_shutdown",
        )
        assert journal(tmp_path) == [f"final:{child.pid}"]
        assert not service.is_alive and INFERENCE_ENDPOINT_ENV not in os.environ
    assert not pid_exists(child.pid)


async def test_host_keeps_shared_inference_while_execution_children_remain(
    tmp_path: Path, socket_root: Path, owned_endpoints: set[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    avatar_host = host(tmp_path)
    async with shared_inference(tmp_path, owned_endpoints) as service:
        avatar_host._inference = service
        await avatar_host._health.on_start()
        port = avatar_host._health.port
        # An unreaped child could still be using the endpoint: model it at the supervisor boundary.
        monkeypatch.setattr(ProcessSupervisor, "all_reaped", property(lambda _: False))

        with pytest.raises(ExceptionGroup) as failed:
            async with asyncio.timeout(HANG_GUARD):
                await avatar_host.aclose()
        assert failed.group_contains(RuntimeError, match="Execution children remain")
        assert service.observed == [] and service.is_alive
        # The refused release does not skip later cleanup: the health listener is closed.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
