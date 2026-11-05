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
"""Memory extraction input, checkpoints and shutdown order on a real SQLite workspace."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import alphaavatar.plugins.memory  # noqa: F401  Registers the default Memory plugin.
from alphaavatar.agents.avatar.provider.base import LLMBase
from alphaavatar.agents.avatar.provider.enums import ModelRole
from alphaavatar.agents.avatar.provider.records import model_record_batch
from alphaavatar.agents.avatar.provider.schemas.model_input import (
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelInputMessage,
    ModelTextPart,
)
from alphaavatar.agents.avatar.provider.schemas.model_result import ProviderModelResult
from alphaavatar.agents.memory.enums import MemoryOwnerKind, MemoryScopeKind, MemoryType
from alphaavatar.agents.memory.schemas import (
    MemoryCheckpointAdvance,
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryScope,
)
from alphaavatar.agents.memory.store import MemoryCheckpointConflict, MemoryStoreConflict
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.modules.foundation import ProviderService
from alphaavatar.agents.runtime.modules.participants import ParticipantRuntime
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
from alphaavatar.agents.workspace import WorkspacePaths, prepare_session_path, prepare_workspace
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import PerceptionSourceRef
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.output.schemas import OutputScope
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.session.enums import IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import IdentityBasis, IdentityRequest
from alphaavatar.core.time import RuntimeTimeRange
from alphaavatar.core.turn import TurnRuntime
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef, TurnSnapshot
from alphaavatar.plugins.memory.processors.environment.config import EnvironmentSchedulerConfig
from alphaavatar.plugins.memory.processors.environment.scheduler import EnvMemoryScheduler
from alphaavatar.plugins.memory.schemas.patch import MemoryDelta, PatchOp
from alphaavatar.plugins.memory.state import MemoryContextState
from alphaavatar.plugins.memory.storage.sqlite import SQLiteMemoryStore

HANG_GUARD = 30
Script = Callable[[str], Awaitable[MemoryDelta]]


class ScriptedLLM(LLMBase):
    """Offline structured model; each configured task model name selects one script."""

    def __init__(self, script: Script) -> None:
        self.script, self.prompts = script, []

    def validate_input(self, *, require_input_adapter: bool = False) -> None:
        pass

    async def ainvoke_structured(self, model_input, *, output_schema, include_raw=False):
        prompt = "\n".join(item.text or "" for item in model_input.items)
        self.prompts.append(prompt)
        return ProviderModelResult(output=await self.script(prompt))

    async def aclose(self) -> None:
        pass


class ScriptedProviders(ProviderService):
    def __init__(self, **scripts: Script) -> None:
        super().__init__()
        self.models = {name: ScriptedLLM(script) for name, script in scripts.items()}

    def model(self, config):
        self._ensure_open()
        return self.models[config.model]


class RecordingInference:
    """In-process stand-in for the Memory VDB runner transport."""

    def __init__(self) -> None:
        self.operations: list[str] = []

    async def do_inference(self, method: str, data: bytes) -> bytes:
        request = json.loads(data)
        self.operations.append(request["op"])
        if request["op"] == "search_similar_batch":
            return json.dumps({"results": [[] for _ in request["param"]["texts"]]}).encode()
        return json.dumps({"candidates": [], "saved": True}).encode()

    async def close(self) -> None:
        pass


async def empty(prompt: str) -> MemoryDelta:
    return MemoryDelta()


def gateway(model: str) -> dict:
    return {"trace": {"enabled": False}, "tasks": {"task": {"model": model}}}


def avatar_runtime(root: Path, providers: ProviderService) -> AvatarRuntime:
    workspace = WorkspacePaths.from_root(root / "avatar")
    prepare_workspace(workspace)
    session = SessionRuntime(session_id="session")
    session_path = workspace.data.sessions.get("session", date(2026, 11, 2))
    prepare_session_path(session_path)
    perception = PerceptionRuntime(
        session_id="session",
        stream_maxlens=dict.fromkeys(PerceptionStreamKind, 64),
        clock=session.clock,
    )
    # A short Turn window proves Memory retains its own references to unextracted input.
    turn = TurnRuntime(perception=perception, max_snapshots=16, event_maxlen=512)
    return AvatarRuntime(
        clock=session.clock,
        workspace=workspace,
        session_path=session_path,
        session=session,
        perception=perception,
        turn=turn,
        output=OutputRuntime(session_id="session", clock=session.clock),
        state=StateRuntime(),
        participants=ParticipantRuntime(session=session, workspace=workspace, turn=turn),
        inference=RecordingInference(),
        foundation=SimpleNamespace(provider=providers, aclose=providers.aclose),
    )


def memory_for(runtime: AvatarRuntime):
    return AvatarModulePlugin.create(
        AvatarModule.MEMORY,
        "default",
        runtime=runtime,
        avatar_id="avatar",
        maximum_memory_num=24,
        vdb_config={},
        init_config={
            "retrieval": {"enabled": False},
            "conversation": {
                "provider": {"task": "task", "gateway": gateway("conversation")},
                "pipeline": {"consolidation": {"mode": "off"}},
            },
            "tool": {"provider": {"task": "task", "gateway": gateway("tool")}},
        },
    )


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.001)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


async def checkpoint(runtime: AvatarRuntime, context_id: str, processor: str) -> int:
    backend = SQLiteMemoryStore(runtime.workspace.data.memory.records_file)
    await backend.initialize()
    return await backend.get_checkpoint(context_id=context_id, processor=processor)


def commit_turn(runtime: AvatarRuntime, actor: TurnEntityRef, index: int, text: str, *contexts):
    return runtime.turn.commit_input(
        input_id=f"input-{index}",
        modality=TurnInputModality.TEXT,
        text=text,
        actors=(actor,),
        context_ids=contexts,
    )


def speaker(runtime: AvatarRuntime) -> TurnEntityRef:
    participant = runtime.participants.join(user_id="alice", primary=True)
    return TurnEntityRef(
        participant_id=participant.participant_id,
        user_id=participant.user_id,
        identity_sequence=participant.identity_sequence,
    )


def memory_tasks() -> set[asyncio.Task]:
    return {task for task in asyncio.all_tasks() if task.get_name().startswith("memory")}


@pytest.mark.parametrize("outcome", ["provider-failure", "empty-success"])
async def test_failed_extraction_keeps_checkpoint_and_input_while_empty_success_advances(
    outcome: str, tmp_path: Path
) -> None:
    async def conversation(prompt: str) -> MemoryDelta:
        if outcome == "provider-failure":
            raise ConnectionError("provider offline")
        return MemoryDelta()

    runtime = avatar_runtime(tmp_path, ScriptedProviders(conversation=conversation, tool=empty))
    memory, actor = memory_for(runtime), speaker(runtime)
    await memory.on_start()
    snapshots = [commit_turn(runtime, actor, index, f"fact {index}") for index in range(2)]
    state = memory.context_state(memory.root_context_id)
    await wait_until(lambda: state.message_sequence == 2, "Memory never received both Turns")

    if outcome == "provider-failure":
        with pytest.raises(ExceptionGroup) as failed:
            await memory.on_stop()
        assert failed.group_contains(ConnectionError)
    else:
        await memory.on_stop()

    expected = 0 if outcome == "provider-failure" else 2
    assert await checkpoint(runtime, state.context_id, "conversation") == expected
    # The tool extractor has no tool evidence; its empty success still acknowledges input.
    assert await checkpoint(runtime, state.context_id, "tool") == 2
    assert all(
        held is snapshot
        for held, snapshot in zip(state.messages_between(0, 2), snapshots, strict=True)
    )
    assert not memory_tasks()
    await runtime.aclose()


async def test_finalization_extracts_complete_untruncated_input_without_background_updates(
    tmp_path: Path,
) -> None:
    runtime = avatar_runtime(tmp_path, ScriptedProviders(conversation=empty, tool=empty))
    memory, actor = memory_for(runtime), speaker(runtime)
    await memory.on_start()

    oversized = "".join(f"<{index:05d}>" for index in range(6000))
    first = commit_turn(runtime, actor, 0, oversized)
    runtime.output.publish_records(
        model_record_batch(
            batch_id="records-0",
            source="test",
            scope=OutputScope(context_id=memory.root_context_id, turn_id=first.turn_id),
            identity_basis=runtime.participants.identity_basis(first),
            items=(
                ModelInputMessage(
                    id="assistant-0", role=ModelRole.ASSISTANT, parts=(ModelTextPart("noted"),)
                ),
                ModelFunctionCall(id="call-0", call_id="c0", name="lookup", arguments='{"q":1}'),
                ModelFunctionOutput(
                    id="output-0",
                    call_id="c0",
                    name="lookup",
                    parts=(ModelTextPart("tool says hi"),),
                    is_error=False,
                ),
            ),
        )
    )
    later = [commit_turn(runtime, actor, index, f"turn {index}") for index in range(1, 151)]
    state = memory.context_state(memory.root_context_id)
    await wait_until(lambda: state.message_sequence == 154, "Memory did not retain every input")
    for _ in range(10):
        await asyncio.sleep(0)

    models = runtime.foundation.provider.models
    assert not models["conversation"].prompts and not models["tool"].prompts
    held = [item for item in state.messages if isinstance(item, TurnSnapshot)]
    assert all(left is right for left, right in zip(held, [first, *later], strict=True))
    # Core already evicted the early Turn; Memory still owns its unextracted reference.
    assert runtime.turn.get(first.input_id) is None

    await memory.on_stop()
    (conversation,) = models["conversation"].prompts
    (tool,) = models["tool"].prompts
    assert oversized in conversation and "turn 150" in conversation
    assert '{"q":1}' in tool and "tool says hi" in tool and oversized in tool
    for processor in ("conversation", "tool"):
        assert await checkpoint(runtime, state.context_id, processor) == 154
    await runtime.aclose()


@pytest.mark.parametrize("failure", [RuntimeError("extraction failed"), asyncio.CancelledError()])
async def test_failed_or_cancelled_context_waits_for_all_finalization_before_store_closes(
    failure: BaseException, tmp_path: Path
) -> None:
    entered, failed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def conversation(prompt: str) -> MemoryDelta:
        if "side context" in prompt:
            entered.set()
            await release.wait()
            return MemoryDelta()
        failed.set()
        raise failure

    runtime = avatar_runtime(tmp_path, ScriptedProviders(conversation=conversation, tool=empty))
    memory, actor = memory_for(runtime), speaker(runtime)
    await memory.on_start()
    root = memory.context_state(memory.root_context_id)
    side = memory.open_context(
        context=MemoryContextRef(
            episode_id=root.context.episode_id,
            context_id="side",
            session_id="session",
            parent_context_id=root.context_id,
        ),
        provider_dir=runtime.session_path.provider_dir,
        owner_refs=[MemoryOwnerRef.avatar("avatar")],
    )
    commit_turn(runtime, actor, 0, "root context")
    commit_turn(runtime, actor, 1, "side context", "side")
    await wait_until(
        lambda: root.message_sequence == side.message_sequence == 1, "Turns were not routed"
    )

    stopping = asyncio.create_task(memory.on_stop())
    async with asyncio.timeout(HANG_GUARD):
        await asyncio.gather(entered.wait(), failed.wait())
    for _ in range(10):
        await asyncio.sleep(0)
    # The failed context has settled, yet the Store stays open for the other one: its
    # finalization still commits after the release below.
    assert not stopping.done()

    release.set()
    with pytest.raises(ExceptionGroup) as stopped:
        await stopping
    assert stopped.group_contains(type(failure) if isinstance(failure, Exception) else RuntimeError)
    assert await checkpoint(runtime, "side", "conversation") == 1
    assert await checkpoint(runtime, root.context_id, "conversation") == 0
    assert await checkpoint(runtime, root.context_id, "tool") == 1
    assert not memory_tasks()
    await runtime.aclose()


def tool_records(
    runtime: AvatarRuntime,
    context_id: str,
    snapshot: TurnSnapshot,
    tag: str,
    basis: IdentityBasis | None = None,
) -> None:
    runtime.output.publish_records(
        model_record_batch(
            batch_id=f"records-{tag}",
            source="test",
            scope=OutputScope(context_id=context_id, turn_id=snapshot.turn_id),
            identity_basis=runtime.participants.identity_basis(snapshot)
            if basis is None
            else basis,
            items=(
                ModelFunctionCall(
                    id=f"call-{tag}", call_id=f"c-{tag}", name="lookup", arguments='{"q":2}'
                ),
                ModelFunctionOutput(
                    id=f"output-{tag}",
                    call_id=f"c-{tag}",
                    name="lookup",
                    parts=(ModelTextPart(f"<{tag} result>"),),
                    is_error=False,
                ),
            ),
        )
    )


def open_side(runtime: AvatarRuntime, memory, *participants) -> MemoryContextState:
    root = memory.context_state(memory.root_context_id)
    return memory.open_context(
        context=MemoryContextRef(
            episode_id=root.context.episode_id,
            context_id="side",
            session_id="session",
            parent_context_id=root.context_id,
        ),
        provider_dir=runtime.session_path.provider_dir,
        owner_refs=[MemoryOwnerRef.avatar("avatar")],
        participants=participants,
    )


async def test_failed_tool_extraction_keeps_its_checkpoint_and_surfaces_at_close(
    tmp_path: Path,
) -> None:
    async def tool(prompt: str) -> MemoryDelta:
        raise ConnectionError("tool provider offline")

    runtime = avatar_runtime(tmp_path, ScriptedProviders(conversation=empty, tool=tool))
    memory, actor = memory_for(runtime), speaker(runtime)
    await memory.on_start()
    turn = commit_turn(runtime, actor, 0, "look this up")
    tool_records(runtime, memory.root_context_id, turn, "root")
    state = memory.context_state(memory.root_context_id)
    await wait_until(lambda: state.message_sequence == 3, "Memory never received the tool records")
    held = state.messages_between(0, 3)

    with pytest.raises(ExceptionGroup) as failed:
        await memory.on_stop()
    assert failed.group_contains(ConnectionError)
    assert await checkpoint(runtime, state.context_id, "tool") == 0
    # The failed processor does not stop another processor's finalization.
    assert await checkpoint(runtime, state.context_id, "conversation") == 3
    assert held[0] is turn
    assert all(
        left is right for left, right in zip(state.messages_between(0, 3), held, strict=True)
    )
    assert not memory.memory_state.get(memory_type=MemoryType.TOOLS)
    assert not memory_tasks()
    await runtime.aclose()


@pytest.mark.parametrize(
    "failure", [RuntimeError("tool failed"), asyncio.CancelledError()], ids=["error", "cancelled"]
)
async def test_tool_failure_in_one_context_never_fail_fasts_the_other_contexts(
    failure: BaseException, tmp_path: Path
) -> None:
    entered, failed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def tool(prompt: str) -> MemoryDelta:
        if "<side result>" in prompt:
            entered.set()
            await release.wait()
            return MemoryDelta(user_or_tool_memory_entries=[PatchOp(value="side lookup kept")])
        failed.set()
        raise failure

    runtime = avatar_runtime(tmp_path, ScriptedProviders(conversation=empty, tool=tool))
    memory, actor = memory_for(runtime), speaker(runtime)
    await memory.on_start()
    root, side = memory.context_state(memory.root_context_id), open_side(runtime, memory)
    tool_records(runtime, root.context_id, commit_turn(runtime, actor, 0, "root context"), "root")
    tool_records(runtime, "side", commit_turn(runtime, actor, 1, "side context", "side"), "side")
    await wait_until(
        lambda: root.message_sequence == side.message_sequence == 3, "Records were not routed"
    )
    (processor,) = (item for item in memory._processors if item.name == "tool")

    stopping = asyncio.create_task(memory.on_stop())
    async with asyncio.timeout(HANG_GUARD):
        await asyncio.gather(entered.wait(), failed.wait())
    for _ in range(20):
        await asyncio.sleep(0)
    # The failed context has settled; Tool finalization and the Store stay open, as the
    # checkpoints committed after the release below show.
    assert processor.started and not stopping.done()

    release.set()
    with pytest.raises(ExceptionGroup) as stopped:
        await stopping
    assert stopped.group_contains(type(failure) if isinstance(failure, Exception) else RuntimeError)
    for context_id, name, expected in (
        ("side", "tool", 3),
        ("side", "conversation", 3),
        (root.context_id, "conversation", 3),
        (root.context_id, "tool", 0),
    ):
        assert await checkpoint(runtime, context_id, name) == expected
    (item,) = memory.memory_state.get(memory_type=MemoryType.TOOLS)
    assert (item.value, item.context.context_id) == ("side lookup kept", "side")
    assert not memory_tasks()
    await runtime.aclose()


def correct(runtime: AvatarRuntime, participant_id: str, user_id: str) -> None:
    current = runtime.participants.get(participant_id)
    request = IdentityRequest(
        participant_id=participant_id,
        user_id=user_id,
        source=IdentitySource.AGENT,
        basis_sequence=current.identity_sequence,
        reason="The user corrected their name",
    )
    assert runtime.participants.bind_user(request) is IdentityOutcome.APPLIED


@pytest.mark.parametrize("correction", ["none", "before-execution", "after-execution"])
async def test_model_records_are_attributed_by_their_own_identity_basis(
    correction: str, tmp_path: Path
) -> None:
    async def tool(prompt: str) -> MemoryDelta:
        return MemoryDelta(user_or_tool_memory_entries=[PatchOp(value="prefers window seats")])

    runtime = avatar_runtime(tmp_path, ScriptedProviders(conversation=empty, tool=tool))
    memory, actor = memory_for(runtime), speaker(runtime)
    await memory.on_start()
    # Agent tool work is recorded in a child context; the user's Turn lives in the parent.
    side = open_side(runtime, memory, *runtime.session.participants.values())
    turn = commit_turn(runtime, actor, 0, "book my usual seat")
    if correction == "before-execution":
        correct(runtime, actor.participant_id, "bob")
    basis = runtime.participants.identity_basis(turn)  # Captured when the execution starts.
    if correction == "after-execution":
        correct(runtime, actor.participant_id, "bob")
    tool_records(runtime, "side", turn, "side", basis=basis)
    await wait_until(lambda: side.message_sequence == 2, "Memory never received the records")
    await memory.on_stop()

    (item,) = memory.memory_state.get(memory_type=MemoryType.TOOLS)
    (ref,) = basis.participants
    # Durable evidence keeps the record's own basis, not the Turn's or the current identity.
    assert item.extra_data["session_identity"]["actors"] == [
        {
            "participant_id": ref.participant_id,
            "user_id": ref.user_id,
            "identity_sequence": ref.identity_sequence,
        }
    ]
    owners = {(owner.kind, owner.id) for owner in item.owner_refs}
    if correction == "after-execution":
        # A record admitted under a superseded identity never reaches the corrected user.
        assert ref.user_id == "alice"
        assert owners == {(MemoryOwnerKind.AVATAR, "avatar")}
        assert item.scope.kind is MemoryScopeKind.CONTEXT and item.extra_data["unattributed_input"]
    else:
        assert ref.user_id == ("bob" if correction == "before-execution" else "alice")
        assert owners == {(MemoryOwnerKind.USER, ref.user_id)}
        assert item.scope.kind is MemoryScopeKind.OWNER
        assert "unattributed_input" not in item.extra_data
    await runtime.aclose()


def text_event(perception: PerceptionRuntime) -> None:
    now = perception.clock.now()
    perception.publish_observation(
        EnvObservation(
            kind=ObservationKind.TEXT_INPUT,
            time_range=RuntimeTimeRange.point(now),
            source=PerceptionSourceRef("keyboard", 1),
        )
    )


@pytest.mark.parametrize("attempts", [2, 1], ids=["recovered", "exhausted"])
async def test_env_retry_keeps_its_own_range_and_never_absorbs_a_newer_batch(
    attempts: int, tmp_path: Path
) -> None:
    perception = PerceptionRuntime(
        session_id="session", stream_maxlens=dict.fromkeys(PerceptionStreamKind, 64)
    )
    state = MemoryContextState(
        context=MemoryContextRef(episode_id="episode", context_id="context", session_id="session"),
        provider_dir=tmp_path,
        owner_refs=[MemoryOwnerRef.avatar("avatar")],
    )
    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[tuple[int, int, int]] = []

    async def process(batch, timeout: float) -> None:
        calls.append((batch.from_sequence, batch.to_sequence, batch.attempts))
        if len(calls) == 1:
            entered.set()
            await release.wait()
            raise ConnectionError("extraction failed")

    scheduler = EnvMemoryScheduler(
        perception_runtime=perception,
        context_state=state,
        initial_cutoff=perception.capture_cutoff(),
        process=process,
        render_messages=lambda messages: None,
        include_audio=False,
        config=EnvironmentSchedulerConfig(max_attempts=attempts),
    )
    await scheduler.start()
    for _ in range(3):
        text_event(perception)
    scheduler.request("first")
    async with asyncio.timeout(HANG_GUARD):
        await entered.wait()
    for _ in range(2):
        text_event(perception)
    scheduler.request("second")
    await wait_until(
        lambda: scheduler.status["pending_batches"] == 1, "The newer batch was not captured"
    )

    release.set()
    if attempts == 2:
        await wait_until(
            lambda: scheduler.status["committed_sequence"] == 5, "ENV did not recover in order"
        )
        assert calls == [(0, 3, 1), (0, 3, 2), (3, 5, 1)]
    else:
        await wait_until(lambda: scheduler.status["state"] == "failed", "ENV failure not surfaced")
        assert scheduler.status["failure"] == "retry_exhausted"
    await scheduler.stop(finalize=True)
    if attempts == 1:
        # The failed range stays unacknowledged; its successor is never committed over the hole.
        assert calls == [(0, 3, 1)]
        assert scheduler.status["committed_sequence"] == 0


async def test_env_durable_replay_cannot_rewind_or_overwrite_a_newer_checkpoint(
    tmp_path: Path,
) -> None:
    runtime = avatar_runtime(tmp_path, ScriptedProviders(conversation=empty, tool=empty))
    memory = memory_for(runtime)
    await memory.store.start()
    context = MemoryContextRef(episode_id="episode", context_id="context", session_id="session")

    def batch(value: str) -> list[MemoryItem]:
        return [
            MemoryItem(
                context=context,
                scope=MemoryScope.context("context"),
                owner_refs=[MemoryOwnerRef.avatar("avatar")],
                value=value,
                memory_type=MemoryType.ENV,
            )
        ]

    async def commit(items: list[MemoryItem], start: int, end: int, key: str | None = None):
        return await memory.store.commit(
            items,
            context_id="context",
            processor="environment",
            idempotency_key=key or f"context:environment:{start}:{end}",
            checkpoint=MemoryCheckpointAdvance(from_sequence=start, to_sequence=end),
        )

    older, newer = batch("lamp turned on"), batch("door opened")
    await commit(older, 0, 3)
    await commit(newer, 3, 5)
    assert (await commit(older, 0, 3)).duplicate
    with pytest.raises(MemoryStoreConflict):
        await commit(batch("re-extracted lamp"), 0, 3)
    with pytest.raises(MemoryCheckpointConflict):
        await commit(batch("lamp again"), 0, 3, key="recovery")
    assert await checkpoint(runtime, "context", "environment") == 5
    stored = await memory.store.get_many([item.memory_id for item in (*older, *newer)])
    assert sorted(item.value for item in stored) == ["door opened", "lamp turned on"]
    await memory.store.stop()
    await runtime.aclose()


async def extract_under_load(root: Path) -> int:
    runtime = avatar_runtime(root, ScriptedProviders(conversation=empty, tool=empty))
    memory, actor = memory_for(runtime), speaker(runtime)
    await memory.on_start()
    expected = 0
    for index in range(300):
        snapshot = commit_turn(runtime, actor, index, f"<turn {index}>")
        expected += 1
        if index % 3 == 0:
            runtime.output.publish_records(
                model_record_batch(
                    batch_id=f"records-{index}",
                    source="test",
                    scope=OutputScope(context_id=memory.root_context_id, turn_id=snapshot.turn_id),
                    identity_basis=runtime.participants.identity_basis(snapshot),
                    items=(
                        ModelInputMessage(
                            id=f"reply-{index}",
                            role=ModelRole.ASSISTANT,
                            parts=(ModelTextPart(f"<reply {index}>"),),
                        ),
                    ),
                )
            )
            expected += 1
        if index % 50 == 0:
            await asyncio.sleep(0)
    state = memory.context_state(memory.root_context_id)
    await wait_until(lambda: state.message_sequence == expected, "Memory lost input under load")
    await memory.on_stop()
    (prompt,) = runtime.foundation.provider.models["conversation"].prompts
    assert all(f"<turn {index}>" in prompt for index in range(300))
    assert all(f"<reply {index}>" in prompt for index in range(0, 300, 3))
    assert await checkpoint(runtime, state.context_id, "conversation") == expected
    await runtime.aclose()
    return expected


@pytest.mark.stress
async def test_sustained_turns_and_records_are_all_extracted_once_at_close(
    tmp_path: Path, stress_seconds: float
) -> None:
    deadline, rounds, inputs = time.monotonic() + stress_seconds, 0, 0
    while rounds == 0 or time.monotonic() < deadline:
        inputs += await extract_under_load(tmp_path / f"round-{rounds}")
        rounds += 1
    print(f"memory stress rounds={rounds} inputs={inputs} seconds={stress_seconds}")
