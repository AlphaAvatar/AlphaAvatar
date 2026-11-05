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
"""Passive recall reports each Turn's concrete outcome to the Turn input trace, once."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import alphaavatar.plugins.memory  # noqa: F401  Registers the default Memory plugin.
from alphaavatar.agents.memory.enums import MemoryType, VectorRunnerOP
from alphaavatar.agents.memory.schemas import MemoryItem, MemoryOwnerRef, MemoryScope
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.modules.foundation import ProviderService
from alphaavatar.agents.runtime.modules.participants import ParticipantRuntime
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
from alphaavatar.agents.workspace import WorkspacePaths, prepare_session_path, prepare_workspace
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.session.enums import IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import IdentityRequest
from alphaavatar.core.turn import TurnRuntime
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef, TurnSnapshot

HANG_GUARD = 30


class RecallInference:
    """In-process VDB transport; context searches follow the test's gate and reply."""

    def __init__(self) -> None:
        self.gate, self.entered = asyncio.Event(), asyncio.Event()
        self.gate.set()
        self.reply: Callable[[], dict] = lambda: {"candidates": []}

    async def do_inference(self, method: str, data: bytes) -> bytes:
        request = json.loads(data)
        if request["op"] == VectorRunnerOP.search_by_context:
            self.entered.set()
            await self.gate.wait()
            return json.dumps(self.reply()).encode()
        if request["op"] == VectorRunnerOP.search_similar_batch:
            return json.dumps({"results": [[] for _ in request["param"]["texts"]]}).encode()
        return json.dumps({"candidates": [], "saved": True}).encode()

    async def close(self) -> None:
        pass


class Recall(SimpleNamespace):
    runtime: AvatarRuntime
    inference: RecallInference
    actor: TurnEntityRef

    def commit(self, index: int, text: str = "Where should we eat tonight?") -> TurnSnapshot:
        return self.runtime.turn.commit_input(
            input_id=f"input-{index}",
            modality=TurnInputModality.TEXT,
            text=text,
            actors=(self.actor,),
        )

    def outcomes(self) -> list[list[tuple[str, int]]]:
        """Recall outcomes per committed Turn, in commit order, joined by the hashed Turn id."""
        records = self.runtime.perception.input_trace.snapshot().to_dict()["records"]
        turns = [record["turn_id"] for record in records if record["stage"] == "turn.committed"]
        return [
            [
                (record["outcome"], record["evidence_count"])
                for record in records
                if record["stage"] == "memory.recall" and record["turn_id"] == turn
            ]
            for turn in turns
        ]

    async def settled(self, count: int) -> list[list[tuple[str, int]]]:
        async with asyncio.timeout(HANG_GUARD):
            while sum(map(len, outcomes := self.outcomes())) < count:
                await asyncio.sleep(0.001)
        return outcomes


@pytest.fixture
async def recall(request: pytest.FixtureRequest, tmp_path: Path):
    workspace = WorkspacePaths.from_root(tmp_path / "avatar")
    prepare_workspace(workspace)
    session = SessionRuntime(session_id="session")
    session_path = workspace.data.sessions.get("session", date(2026, 11, 2))
    prepare_session_path(session_path)
    perception = PerceptionRuntime(
        session_id="session",
        stream_maxlens=dict.fromkeys(PerceptionStreamKind, 64),
        clock=session.clock,
    )
    turn = TurnRuntime(perception=perception, max_snapshots=16, event_maxlen=64)
    providers, inference = ProviderService(), RecallInference()
    runtime = AvatarRuntime(
        clock=session.clock,
        workspace=workspace,
        session_path=session_path,
        session=session,
        perception=perception,
        turn=turn,
        output=OutputRuntime(session_id="session", clock=session.clock),
        state=StateRuntime(),
        participants=ParticipantRuntime(session=session, workspace=workspace, turn=turn),
        inference=inference,
        foundation=SimpleNamespace(provider=providers, aclose=providers.aclose),
    )
    retrieval = {
        "enabled": True,
        "passive_timeout_sec": HANG_GUARD,
        **getattr(request, "param", {}),
    }
    memory = AvatarModulePlugin.create(
        AvatarModule.MEMORY,
        "default",
        runtime=runtime,
        avatar_id="avatar",
        maximum_memory_num=24,
        vdb_config={},
        init_config={
            "retrieval": retrieval,
            "conversation": {"enabled": False},
            "tool": {"enabled": False},
        },
    )
    participant = runtime.participants.join(user_id="alice", primary=True)
    actor = TurnEntityRef(
        participant_id=participant.participant_id,
        user_id=participant.user_id,
        identity_sequence=participant.identity_sequence,
    )
    await memory.on_start()
    state = Recall(runtime=runtime, inference=inference, actor=actor, memory=memory)
    try:
        yield state
    finally:
        inference.gate.set()
        await memory.on_stop()
        await runtime.aclose()


async def test_completed_recall_reports_its_items_or_an_empty_result(recall: Recall) -> None:
    state = recall.memory.context_state(recall.memory.root_context_id)
    (item,) = items = [
        MemoryItem(
            context=state.context,
            scope=MemoryScope.context(state.context_id),
            owner_refs=[MemoryOwnerRef.avatar("avatar")],
            value="The user prefers quiet restaurants",
            memory_type=MemoryType.CONVERSATION,
        )
    ]
    await recall.memory.store.commit(
        items, context_id=state.context_id, processor="test", idempotency_key="seed"
    )
    recall.inference.reply = lambda: {"candidates": [{"memory_id": item.memory_id}]}
    first = recall.commit(0)
    assert await recall.runtime.turn.wait_context_ready(first)
    recall.inference.reply = lambda: {"candidates": []}
    second = recall.commit(1)
    assert await recall.runtime.turn.wait_context_ready(second)

    assert await recall.settled(2) == [[("ok", 1)], [("empty", 0)]]
    # Bounded metadata only: recalled text never enters the trace.
    serialized = json.dumps(recall.runtime.perception.input_trace.snapshot().to_dict())
    assert "quiet restaurants" not in serialized and "Where should we eat" not in serialized


@pytest.mark.parametrize("recall", [{"passive_timeout_sec": 0.2}], indirect=True)
async def test_timed_out_recall_keeps_its_deadline_and_reports_timeout(recall: Recall) -> None:
    recall.inference.gate.clear()
    snapshot = recall.commit(0)
    ready = asyncio.create_task(recall.runtime.turn.wait_context_ready(snapshot))
    async with asyncio.timeout(HANG_GUARD):
        await recall.inference.entered.wait()
    await asyncio.sleep(0)
    # The latch still holds readiness until the recall's own deadline.
    assert not ready.done() and recall.outcomes() == [[]]
    assert await ready
    assert await recall.settled(1) == [[("timeout", 0)]]


@pytest.mark.parametrize(
    "recall",
    [
        {"max_pending_recalls": 1, "max_retained_turns": 2},
        {"max_pending_recalls": 1, "max_retained_turns": 1},
    ],
    ids=["pending-limit", "retained-limit"],
    indirect=True,
)
async def test_overloaded_recall_is_reported_without_waiting(recall: Recall) -> None:
    recall.inference.gate.clear()
    first = recall.commit(0)
    async with asyncio.timeout(HANG_GUARD):
        await recall.inference.entered.wait()
    second = recall.commit(1)
    # The overloaded Turn is ready at once while the first recall still holds its slot.
    assert await recall.runtime.turn.wait_context_ready(second)
    assert await recall.settled(1) == [[], [("overloaded", 0)]]
    recall.inference.gate.set()
    assert await recall.runtime.turn.wait_context_ready(first)
    assert await recall.settled(2) == [[("empty", 0)], [("overloaded", 0)]]


async def test_failed_recall_reports_error(recall: Recall) -> None:
    def fail() -> dict:
        raise RuntimeError("vector index unavailable")

    recall.inference.reply = fail
    snapshot = recall.commit(0)
    assert await recall.runtime.turn.wait_context_ready(snapshot)
    assert await recall.settled(1) == [[("error", 0)]]


async def test_identity_change_during_recall_is_reported(recall: Recall) -> None:
    recall.inference.gate.clear()
    snapshot = recall.commit(0)
    ready = asyncio.create_task(recall.runtime.turn.wait_context_ready(snapshot))
    async with asyncio.timeout(HANG_GUARD):
        await recall.inference.entered.wait()
    request = IdentityRequest(
        participant_id=recall.actor.participant_id,
        user_id="bob",
        source=IdentitySource.AGENT,
        basis_sequence=recall.actor.identity_sequence,
        reason="The user corrected their name",
    )
    assert recall.runtime.participants.bind_user(request) is IdentityOutcome.APPLIED
    recall.inference.gate.set()
    assert await ready
    assert await recall.settled(1) == [[("identity_changed", 0)]]


async def test_recall_stopped_in_flight_is_reported_unavailable(recall: Recall) -> None:
    recall.inference.gate.clear()
    snapshot = recall.commit(0)
    ready = asyncio.create_task(recall.runtime.turn.wait_context_ready(snapshot))
    async with asyncio.timeout(HANG_GUARD):
        await recall.inference.entered.wait()
    await recall.memory.on_stop()
    assert await ready
    assert await recall.settled(1) == [[("unavailable", 0)]]
