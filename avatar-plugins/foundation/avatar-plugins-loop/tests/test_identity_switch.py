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
"""Real Loop, Context and Output under identity changes; only the model provider is scripted."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pytest
from pydantic import BaseModel

from alphaavatar.agents.avatar.loop.enums import LoopState, ToolOutcome
from alphaavatar.agents.avatar.loop.schemas import LoopRequest, LoopResult
from alphaavatar.agents.avatar.provider.enums import ModelFinishReason, ModelRole
from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelInputMessage,
    ModelRequest,
    ModelTextPart,
)
from alphaavatar.agents.avatar.provider.schemas.stream import (
    ModelItemCompleted,
    ModelResponseCompleted,
    ModelTextDelta,
)
from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.capability import avatar_capability
from alphaavatar.agents.runtime.capability.enums import AvatarCapabilityName
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.agents.runtime.modules.foundation import FoundationRuntime
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.output.enums import OutputControlType, OutputKind
from alphaavatar.core.session import (
    IdentityOutcome,
    IdentityRequest,
    IdentitySource,
    Participant,
    SessionRuntime,
)
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef, TurnSnapshot
from alphaavatar.plugins.loop.config import RealtimeLoopConfig
from alphaavatar.plugins.loop.execution import LoopExecution
from alphaavatar.plugins.loop.loop import AvatarLoop

HANG_GUARD = 30
type Script = Callable[[ModelRequest], AsyncIterator[object]]


class ScriptedProvider:
    """Offline provider boundary: each model request streams the next scripted response."""

    def __init__(self, *scripts: Script) -> None:
        self._scripts = list(scripts)
        self.requests: list[ModelRequest] = []
        self.prepared: list[tuple[str, ...]] = []  # The tasks each preparation named

    def gateway(self, config: object) -> ScriptedProvider:
        return self

    def validate_tasks(self, names: tuple[str, ...], *, require_streaming: bool = False) -> None:
        pass

    def prepare(self, names: Iterable[str]) -> None:
        self.prepared.append(tuple(names))

    @asynccontextmanager
    async def stream(self, *, task_name: str, request: ModelRequest) -> AsyncIterator[object]:
        self.requests.append(request)
        events = self._scripts.pop(0)(request)
        try:
            yield events
        finally:
            await events.aclose()

    async def aclose(self) -> None:
        pass


class UserScopedSource:
    """Persona/Memory stand-in rendering the identity the Context asks for, plus a cache revision."""

    def __init__(self, runtime: AvatarRuntime) -> None:
        self._runtime, self.revision = runtime, 0

    def content_for(self, snapshot: TurnSnapshot) -> str:
        actors = self._runtime.participants.project_turn(snapshot).actors
        return " ".join(f"profile-of-{actor.user_id}@{self.revision}" for actor in actors)


class Query(BaseModel):
    query: str


@avatar_capability(
    name=AvatarCapabilityName.MEMORY_RETRIEVAL,
    description="Recall private user memories.",
    input_schema=Query,
)
class GatedRecall:
    """Identity-scoped recall that completes only when the test releases it."""

    def __init__(self) -> None:
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def invoke(self, request: Query, *, input_id: str | None = None) -> str:
        self.entered.set()
        await self.release.wait()
        return "private-memory-of-user-b"


@avatar_capability(name="test.lookup", description="Look something up.", input_schema=Query)
class CacheTouchingLookup:
    """A tool whose execution coincides with an ordinary Persona/Memory cache update."""

    def __init__(self, source: UserScopedSource) -> None:
        self._source = source

    async def invoke(self, request: Query, *, input_id: str | None = None) -> str:
        self._source.revision += 1
        return "lookup-result"


def completed(request: ModelRequest, *items: object) -> ModelResponseCompleted:
    calls = any(isinstance(item, ModelFunctionCall) for item in items)
    return ModelResponseCompleted(
        request_id=request.request_id,
        response_id=f"response:{request.request_id}",
        items=items,
        finish_reason=ModelFinishReason.TOOL_CALLS if calls else ModelFinishReason.STOP,
    )


def delta(request: ModelRequest, item_id: str, text: str) -> ModelTextDelta:
    return ModelTextDelta(
        request_id=request.request_id,
        response_id=f"response:{request.request_id}",
        item_id=item_id,
        output_index=0,
        content_index=0,
        text=text,
    )


def answer(text: str) -> Script:
    async def script(request: ModelRequest) -> AsyncIterator[object]:
        message = ModelInputMessage(
            id=f"answer:{request.request_id}",
            role=ModelRole.ASSISTANT,
            parts=(ModelTextPart(text),),
        )
        yield delta(request, message.id, text)
        yield ModelItemCompleted(
            request_id=request.request_id,
            response_id=f"response:{request.request_id}",
            output_index=0,
            item=message,
        )
        yield completed(request, message)

    return script


def call(name: str, arguments: dict[str, object]) -> Script:
    async def script(request: ModelRequest) -> AsyncIterator[object]:
        yield completed(
            request,
            ModelFunctionCall(
                id=f"call-item:{name}",
                call_id=f"call:{name}",
                name=name.replace(".", "_"),
                arguments=json.dumps(arguments),
            ),
        )

    return script


def rendered(request: ModelRequest) -> str:
    texts = []
    for item in request.input.items:
        if isinstance(item, ModelInputMessage | ModelFunctionOutput):
            texts.append(item.text or "")
        elif isinstance(item, ModelFunctionCall):
            texts.append(item.arguments)
    return "\n".join(texts)


async def delivered_text(runtime: AvatarRuntime) -> list[str]:
    entries = await runtime.output.timeline.snapshot(kinds=(OutputKind.TEXT_CHUNK,))
    return [entry.content.payload.text for entry in entries]


async def start(
    tmp_path: Path, provider: ScriptedProvider
) -> tuple[AvatarRuntime, UserScopedSource]:
    config = AvatarConfig.model_validate({"avatar": {"id": "avatar-1"}})
    workspace = WorkspacePaths.from_root(tmp_path / "workspace")
    runtime = AvatarRuntime.create(
        workspace=workspace,
        session=SessionRuntime(session_id="session-1"),
        session_path=workspace.data.sessions.get("session-1", date(2026, 1, 1)),
        state=StateRuntime(),
        config=config.runtime,
        inference=InferenceExecutor(str(tmp_path / "unused.sock")),
    )
    context = config.context.get_plugin(runtime=runtime, avatar_config=config)
    loop = AvatarLoop(
        RealtimeLoopConfig(model=ProviderTaskConfig(backend="offline", model="scripted")),
        runtime=runtime,
    )
    runtime.bind_foundation(FoundationRuntime(context=context, loop=loop, provider=provider))
    await loop.initialize()
    source = UserScopedSource(runtime)
    context.bind_sources(memory=source, persona=source)
    runtime.capability_registry.collect(runtime.participants)
    return runtime, source


async def submit(runtime: AvatarRuntime, user_id: str) -> tuple[Participant, TurnSnapshot, object]:
    participant = runtime.participants.join(user_id=user_id, primary=True)
    context_id = runtime.state.context_id
    actor = TurnEntityRef(
        kind="person",
        participant_id=participant.participant_id,
        identity_revision=participant.identity_revision,
        user_id=participant.user_id,
    )
    turn = runtime.turn.commit_input(
        input_id="input-1",
        modality=TurnInputModality.TEXT,
        text="Who am I talking to?",
        actors=(actor,),
        context_ids=(context_id,),
    )
    await runtime.output.start_turn(turn_id=turn.turn_id)
    handle = await runtime.foundation.loop.submit(
        LoopRequest(
            turn=turn,
            context_id=context_id,
            allowed_capabilities=tuple(c.id for c in runtime.capability_registry.capabilities),
        )
    )
    return participant, turn, handle


async def finish(handle: object) -> LoopResult:
    async with asyncio.timeout(HANG_GUARD):
        return await handle.wait()


def correct(runtime: AvatarRuntime, participant: Participant, user_id: str) -> IdentityOutcome:
    return runtime.participants.bind_user(
        IdentityRequest(
            participant_id=participant.participant_id,
            user_id=user_id,
            source=IdentitySource.PERCEPTION,
            expected_revision=participant.identity_revision,
            reason=f"Face recognition matched {user_id}",
        )
    )


async def test_agent_rebinding_lets_its_own_run_continue_under_the_new_identity(
    tmp_path: Path,
) -> None:
    provider = ScriptedProvider(
        call("participant.identity", {"user_id": "user-c", "reason": "The user said they are C"}),
        answer("Nice to meet you, C."),
    )
    runtime, _ = await start(tmp_path, provider)
    try:
        participant, turn, handle = await submit(runtime, "user-a")
        result = await finish(handle)

        assert (result.state, result.reason) == (LoopState.COMPLETED, None)
        (record,) = result.tools
        assert (record.outcome, json.loads(record.output.text)["outcome"]) == (
            ToolOutcome.SUCCEEDED,
            "applied",
        )
        first, second = map(rendered, provider.requests)
        assert "profile-of-user-a@0" in first and "user-c" not in first
        # The run re-prepared its own prefix for C and kept its accepted tool pair.
        assert "profile-of-user-c@0" in second and "profile-of-user-a" not in second
        assert record.call.arguments in second and record.output.text in second
        assert await delivered_text(runtime) == ["Nice to meet you, C."]
        assert runtime.turn.get(turn.input_id).actors == turn.actors
        event = runtime.session.identity_history(participant.participant_id)[-1]
        assert (event.source, event.previous_user_id, event.participant.user_id) == (
            IdentitySource.AGENT,
            "user-a",
            "user-c",
        )
    finally:
        await runtime.aclose()


async def test_late_model_output_for_the_previous_identity_is_never_delivered(
    tmp_path: Path,
) -> None:
    offered, closed = asyncio.Event(), asyncio.Event()

    async def interrupted(request: ModelRequest) -> AsyncIterator[object]:
        try:
            yield delta(request, "early", "Hello B, ")
            # A recognition decision lands between two model events; the next one is late.
            assert correct(runtime, runtime.session.primary_participant, "user-a") is (
                IdentityOutcome.APPLIED
            )
            offered.set()
            yield delta(request, "early", "here is B's private plan.")
            yield completed(request)
        finally:
            closed.set()

    provider = ScriptedProvider(interrupted, answer("Hello A."))
    runtime, _ = await start(tmp_path, provider)
    try:
        _, turn, handle = await submit(runtime, "user-b")
        result = await finish(handle)

        assert result.state is LoopState.COMPLETED and offered.is_set() and closed.is_set()
        assert await delivered_text(runtime) == ["Hello B, ", "Hello A."]
        stopped = await runtime.output.timeline.snapshot(kinds=(OutputKind.CONTROL,))
        assert f"{result.identity.run_id}:early" in {
            target.output_id
            for entry in stopped
            if entry.content.payload.type is OutputControlType.INTERRUPT
            for target in entry.content.payload.targets
        }
        second = rendered(provider.requests[1])
        assert "profile-of-user-a@0" in second and "profile-of-user-b" not in second
        assert "private plan" not in second
        # What B already heard remains accepted history, marked as interrupted.
        (spoken,) = (item for item in result.items if item.id == "early")
        assert (spoken.text, spoken.interrupted) == ("Hello B, ", True)
        assert runtime.turn.get(turn.input_id).actors == turn.actors
    finally:
        await runtime.aclose()


async def test_late_recall_for_the_previous_identity_never_enters_the_new_context(
    tmp_path: Path,
) -> None:
    provider = ScriptedProvider(
        call("memory.retrieval", {"query": "What do you remember about me?"}), answer("Hello A.")
    )
    runtime, _ = await start(tmp_path, provider)
    recall = GatedRecall()
    runtime.capability_registry.collect(recall)
    try:
        participant, _, handle = await submit(runtime, "user-b")
        async with asyncio.timeout(HANG_GUARD):
            await recall.entered.wait()
        assert correct(runtime, participant, "user-a") is IdentityOutcome.APPLIED
        recall.release.set()
        result = await finish(handle)

        assert result.state is LoopState.COMPLETED
        (record,) = result.tools
        assert (record.outcome, record.executed) == (ToolOutcome.FAILED, True)
        assert json.loads(record.output.text)["code"] == "identity_changed"
        committed = [item.text for item in result.items if isinstance(item, ModelFunctionOutput)]
        assert committed and not any("private-memory" in text for text in committed)
        second = rendered(provider.requests[1])
        assert "private-memory" not in second and "profile-of-user-a@0" in second
    finally:
        await runtime.aclose()


async def test_cache_updates_do_not_rewrite_a_captured_prefix(tmp_path: Path) -> None:
    provider = ScriptedProvider(call("test.lookup", {"query": "weather"}), answer("Sunny."))
    runtime, source = await start(tmp_path, provider)
    runtime.capability_registry.collect(CacheTouchingLookup(source))
    try:
        _, _, handle = await submit(runtime, "user-a")
        result = await finish(handle)

        assert result.state is LoopState.COMPLETED and source.revision == 1
        first, second = map(rendered, provider.requests)
        # Without an identity change, the second step reuses the exact captured prefix.
        assert "profile-of-user-a@0" in second and "@1" not in second
        assert second.startswith(first)
    finally:
        await runtime.aclose()


async def test_initialization_prepares_the_loops_model_before_any_request(tmp_path: Path) -> None:
    # O-15: the provider builds its client while the session starts, not in the first request.
    provider = ScriptedProvider(answer("Hello."))
    runtime, _ = await start(tmp_path, provider)
    try:
        assert provider.prepared == [("avatar.loop",)] and provider.requests == []
    finally:
        await runtime.aclose()


async def test_a_run_cancelled_while_it_reaps_its_identity_watch_still_reports_its_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # O-17: Engine closing interrupts a run that has just answered and is reaping its
    # identity watch. The run must still settle into a result, not end cancelled itself, or
    # the run's watcher fails the Engine's close.
    reaping, release = asyncio.Event(), asyncio.Event()

    async def watch(self: LoopExecution) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            reaping.set()
            await release.wait()  # Its reaping takes a turn of the loop, or several.
            raise

    monkeypatch.setattr(LoopExecution, "_watch_identity", watch)
    runtime, _ = await start(tmp_path, ScriptedProvider(answer("Hello.")))
    try:
        _, _, handle = await submit(runtime, "user-a")
        async with asyncio.timeout(HANG_GUARD):
            await reaping.wait()
        runtime.foundation.loop.interrupt(run_id=handle.identity.run_id, reason="engine_closed")
        await asyncio.sleep(0)
        release.set()
        result = await finish(handle)
        assert (result.state, result.reason) == (LoopState.CANCELLED, "engine_closed")
    finally:
        await runtime.aclose()


async def test_a_cancel_after_a_run_has_settled_never_revokes_its_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Engine can cancel a run whose answer is still playing. A run that has settled has its
    # task done: the late cancel changes nothing, and its result stays as it was.
    runtime, _ = await start(tmp_path, ScriptedProvider(answer("Hello.")))
    revoked: list[str] = []
    revoke = runtime.output.revoke_run
    monkeypatch.setattr(
        runtime.output, "revoke_run", lambda run_id: (revoked.append(run_id), revoke(run_id))
    )
    try:
        _, _, handle = await submit(runtime, "user-a")
        result = await finish(handle)
        assert result.state is LoopState.COMPLETED
        accepted = runtime.output.accepts_run(handle.identity.run_id)

        handle.cancel(reason="engine_closed")
        assert revoked == [] and runtime.output.accepts_run(handle.identity.run_id) is accepted
        assert await finish(handle) is result
    finally:
        await runtime.aclose()
