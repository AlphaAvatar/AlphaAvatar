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
"""AvatarRuntime closes consumers while the services they borrow are still usable."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pytest
from inference_runner_samples import EchoRunner

from alphaavatar.agents.avatar.context import ContextManager
from alphaavatar.agents.avatar.loop import Loop
from alphaavatar.agents.avatar.voice import TTSBase, VoiceBundle
from alphaavatar.agents.configs.runtime_config import InferenceConfig, RuntimeConfig
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import InferenceExecutor, InferenceRuntime
from alphaavatar.agents.runtime.modules.foundation import FoundationRuntime
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.session import SessionRuntime

HANG_GUARD = 30
ECHO = EchoRunner.INFERENCE_METHOD


class Consumer:
    """Record what a closing consumer could still use; optionally block or fail afterwards."""

    def __init__(
        self,
        runtime: AvatarRuntime,
        events: list[tuple[str, object]],
        *,
        failure: BaseException | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.runtime, self.events, self.failure, self.gate = runtime, events, failure, gate
        self.closing = asyncio.Event()

    async def aclose(self) -> None:
        self.closing.set()
        if self.gate is not None:
            await self.gate.wait()
        foundation = self.runtime.foundation
        assert foundation is not None
        await self.runtime.output.start_turn(turn_id=f"{type(self).__name__}-final")
        self.events.append(
            (
                type(self).__name__,
                (
                    await self.runtime.inference.do_inference(ECHO, b"final"),
                    await foundation.provider.run(lambda: asyncio.sleep(0, "provider")),
                ),
            )
        )
        if self.failure is not None:
            raise self.failure


class ProbeLoop(Consumer, Loop):
    @property
    def ready(self) -> bool:
        return True

    async def initialize(self) -> None:
        pass

    async def submit(self, request, *, authorize=None):
        raise NotImplementedError

    def interrupt(self, *, run_id: str | None = None, reason: str = "interrupted") -> None:
        pass


class ProbeContext(Consumer, ContextManager):
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


class ProbeTTS(TTSBase):
    closed = False

    @property
    def sample_rate(self) -> int:
        return 24000

    @property
    def num_channels(self) -> int:
        return 1

    def synthesize(self, text: str):
        raise NotImplementedError

    async def aclose(self) -> None:
        self.closed = True


@asynccontextmanager
async def shared_inference(owned_addresses: set[object]) -> AsyncIterator[InferenceRuntime]:
    service = InferenceRuntime(
        {ECHO: EchoRunner},
        mp_ctx=mp.get_context("spawn"),
        config=InferenceConfig(initialize_timeout=HANG_GUARD, close_timeout=1),
    )
    try:
        async with asyncio.timeout(HANG_GUARD):
            await service.start()
        owned_addresses.add(service.socket_path)
        yield service
    finally:
        await service.close()


def avatar_runtime(root: Path, socket_path: str) -> AvatarRuntime:
    session = SessionRuntime(session_id="lifecycle")
    workspace = WorkspacePaths.from_root(root / "workspace")
    return AvatarRuntime.create(
        workspace=workspace,
        session=session,
        session_path=workspace.data.sessions.get(session.session_id, date(2026, 11, 2)),
        state=StateRuntime(),
        config=RuntimeConfig(),
        inference=InferenceExecutor(socket_path),
    )


async def assert_closed(runtime: AvatarRuntime) -> None:
    foundation = runtime.foundation
    assert foundation is not None
    with pytest.raises(RuntimeError, match="Inference executor is closed"):
        await runtime.inference.do_inference(ECHO, b"late")
    with pytest.raises(RuntimeError, match="Provider service is closing or closed"):
        await foundation.provider.run(lambda: asyncio.sleep(0))
    with pytest.raises(RuntimeError, match="OutputRuntime is closed"):
        await runtime.output.start_turn(turn_id="late")
    with pytest.raises(RuntimeError, match="ParticipantRuntime is closed"):
        runtime.participants.join()


async def test_consumers_settle_while_provider_inference_and_output_remain_usable(
    tmp_path: Path, socket_root: Path, owned_addresses: set[object]
) -> None:
    async with shared_inference(owned_addresses) as service:
        runtime = avatar_runtime(tmp_path, service.socket_path)
        events: list[tuple[str, object]] = []
        runtime.bind_foundation(
            FoundationRuntime(
                context=ProbeContext(runtime, events), loop=ProbeLoop(runtime, events)
            )
        )
        async with asyncio.timeout(HANG_GUARD):
            await runtime.aclose()
        # Loop may still need Context; both settle before Provider, Output and Inference close.
        assert events == [
            ("ProbeLoop", (b"final", "provider")),
            ("ProbeContext", (b"final", "provider")),
        ]
        await assert_closed(runtime)
        assert not (tmp_path / "workspace").exists()
        # A session only owns its client; the shared service keeps serving other sessions.
        assert service.is_alive
        other = InferenceExecutor(service.socket_path)
        assert await other.do_inference(ECHO, b"other-session") == b"other-session"
        await other.close()


async def test_failed_or_cancelled_consumer_cleanup_does_not_skip_remaining_resources(
    tmp_path: Path, socket_root: Path, owned_addresses: set[object]
) -> None:
    async with shared_inference(owned_addresses) as service:
        runtime = avatar_runtime(tmp_path, service.socket_path)
        events: list[tuple[str, object]] = []
        tts = ProbeTTS()
        runtime.bind_foundation(
            FoundationRuntime(
                context=ProbeContext(runtime, events, failure=asyncio.CancelledError()),
                loop=ProbeLoop(runtime, events, failure=ValueError("loop cleanup failed")),
                voice=VoiceBundle(tts=tts),
            )
        )
        with pytest.raises(ExceptionGroup) as failed:
            async with asyncio.timeout(HANG_GUARD):
                await runtime.aclose()
        assert failed.group_contains(ValueError, match="loop cleanup failed")
        assert failed.group_contains(RuntimeError, match="ProbeContext cleanup was cancelled")
        assert [name for name, _ in events] == ["ProbeLoop", "ProbeContext"]
        assert tts.closed
        await assert_closed(runtime)
        assert service.is_alive


async def test_cancelled_close_caller_waits_until_every_resource_is_released(
    tmp_path: Path, socket_root: Path, owned_addresses: set[object]
) -> None:
    async with shared_inference(owned_addresses) as service:
        runtime = avatar_runtime(tmp_path, service.socket_path)
        events: list[tuple[str, object]] = []
        gate = asyncio.Event()
        loop = ProbeLoop(runtime, events, gate=gate)
        runtime.bind_foundation(FoundationRuntime(context=ProbeContext(runtime, events), loop=loop))

        closing = asyncio.create_task(runtime.aclose())
        await loop.closing.wait()
        closing.cancel()
        for _ in range(3):
            await asyncio.sleep(0)
        assert not closing.done()
        gate.set()
        async with asyncio.timeout(HANG_GUARD):
            with pytest.raises(asyncio.CancelledError):
                await closing
        # Cancellation surfaced only after the owned cleanup finished in order.
        assert [name for name, _ in events] == ["ProbeLoop", "ProbeContext"]
        await assert_closed(runtime)
        with pytest.raises(RuntimeError, match="closing or closed"):
            runtime.bind_foundation(
                FoundationRuntime(context=ProbeContext(runtime, []), loop=ProbeLoop(runtime, []))
            )
