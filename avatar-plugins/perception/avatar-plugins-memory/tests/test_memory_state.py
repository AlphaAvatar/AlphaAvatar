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
"""A Memory context's state: each committed Turn and model or tool record kept once, in
arrival order, a replay accepted only as it was first recorded; whom each is from; and the
latest memory items of each type."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alphaavatar.agents.avatar.provider.enums import ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas.model_input import (
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelInputMessage,
    ModelTextPart,
)
from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.memory.schemas import (
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryParticipantRef,
)
from alphaavatar.agents.runtime.modules.participants import ParticipantRuntime
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import PerceptionSourceRef
from alphaavatar.core.media import TextPayload
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session import Participant, SessionRuntime
from alphaavatar.core.session.enums import IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import IdentityRequest
from alphaavatar.core.time import RuntimeTimeRange
from alphaavatar.core.turn import TurnRuntime
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnSnapshot
from alphaavatar.plugins.memory.state import MemoryContextState, MemoryState

CONTEXT = MemoryContextRef(episode_id="episode", context_id="context", session_id="session")
AVATAR = MemoryOwnerRef.avatar("avatar")


def participants(tmp_path: Path) -> ParticipantRuntime:
    session = SessionRuntime(session_id="session")
    perception = PerceptionRuntime(
        session_id="session",
        stream_maxlens=dict.fromkeys(PerceptionStreamKind, 64),
        clock=session.clock,
    )
    return ParticipantRuntime(
        session=session,
        workspace=WorkspacePaths.from_root(tmp_path / "workspace"),
        turn=TurnRuntime(perception=perception),
    )


def typed(runtime: ParticipantRuntime, input_id: str, person: Participant) -> TurnSnapshot:
    """What the person typed on a device of their own."""
    device = f"device-{person.participant_id}"
    runtime.bind_device(device, person.participant_id)
    observation = EnvObservation(
        kind=ObservationKind.TEXT_INPUT,
        time_range=RuntimeTimeRange.point(runtime.turn.perception.clock.now()),
        source=PerceptionSourceRef(device, 1),
        payload=TextPayload.create(text=f"text for {input_id}"),
        device_id=device,
    )
    return runtime.turn.commit_input(
        input_id=input_id,
        modality=TurnInputModality.TEXT,
        text=f"text for {input_id}",
        final_observations=(observation,),
        context_ids=("context",),
    )


def state_of(runtime: ParticipantRuntime) -> MemoryContextState:
    state = MemoryContextState(
        context=CONTEXT,
        provider_dir=Path("provider"),
        owner_refs=[AVATAR],
        participant_refs=[MemoryParticipantRef.avatar("avatar")],
        participants=tuple(runtime.session.participants.values()),
    )
    state.sync_identity(runtime.session.snapshot())
    return state


def test_a_contexts_users_are_its_participants_never_fixed_refs(tmp_path: Path) -> None:
    for owners, refs in [
        ([AVATAR, MemoryOwnerRef.user("alice")], []),
        ([AVATAR], [MemoryParticipantRef.user("alice")]),
    ]:
        with pytest.raises(ValueError, match="never fixed refs"):
            MemoryContextState(
                context=CONTEXT, provider_dir=tmp_path, owner_refs=owners, participant_refs=refs
            )
    with pytest.raises(ValueError, match="at least one owner"):
        MemoryContextState(context=CONTEXT, provider_dir=tmp_path, owner_refs=[])


def held(state: MemoryContextState) -> list[str]:
    return [
        item.input_id if isinstance(item, TurnSnapshot) else item.id
        for item in state.messages_between(0, state.message_sequence)
    ]


CALL = ModelFunctionCall(id="call-1", call_id="c-1", name="lookup", arguments='{"q":1}')
RESULT = ModelFunctionOutput(
    id="result-1", call_id="c-1", name="lookup", parts=(ModelTextPart("found"),), is_error=False
)
ANSWER = ModelInputMessage(id="answer-1", role=ModelRole.ASSISTANT, parts=(ModelTextPart("hi"),))


def test_a_record_is_kept_once_and_a_replay_is_accepted_only_as_it_was(tmp_path: Path) -> None:
    runtime = participants(tmp_path)
    alice = runtime.join(user_id="alice", primary=True)
    state, turn = state_of(runtime), typed(runtime, "input-1", alice)
    basis = runtime.identity_basis(turn)
    state.add_turn(turn)
    # A user's message is never a record: user input comes from Turns alone.
    asked = ModelInputMessage(id="asked-1", role=ModelRole.USER, parts=(ModelTextPart("hi"),))
    state.add_messages([asked, CALL, RESULT, ANSWER], turn_id=turn.turn_id, identity_basis=basis)
    assert held(state) == ["input-1", "call-1", "result-1", "answer-1"]

    state.add_messages([CALL, RESULT], turn_id=turn.turn_id, identity_basis=basis)
    for batch, origin, error in [
        ([replace(CALL, arguments='{"q":2}')], (turn.turn_id, basis), "Conflicting Memory item"),
        ([CALL], ("another-turn", basis), "origin cannot change"),
        ([CALL], (turn.turn_id, None), "origin cannot change"),
        ([replace(RESULT, id="result-2", name="search")], (None, None), "names do not match"),
        ([replace(RESULT, id="result-2")], (None, None), "Duplicate Memory tool record"),
        ([replace(ANSWER, id="input-1")], (None, None), "collides with committed user input"),
        # A batch is taken whole or not at all.
        ([replace(ANSWER, id="answer-2"), replace(CALL, arguments="{}")], (None, None), "Conflict"),
    ]:
        with pytest.raises(ModelProtocolError, match=error):
            state.add_messages(batch, turn_id=origin[0], identity_basis=origin[1])
    with pytest.raises(TypeError, match="IdentityBasis"):
        state.add_messages([replace(ANSWER, id="answer-2")], identity_basis=object())
    assert held(state) == ["input-1", "call-1", "result-1", "answer-1"]


def test_a_turn_is_kept_once_and_its_identities_never_name_another_input(tmp_path: Path) -> None:
    runtime = participants(tmp_path)
    alice = runtime.join(user_id="alice", primary=True)
    state, turn = state_of(runtime), typed(runtime, "input-1", alice)
    state.add_turn(turn)
    state.add_turn(turn)
    state.add_messages([ANSWER], turn_id=turn.turn_id)

    for snapshot, error in [
        (replace(turn, input_id="input-2"), "reused for another input"),
        (replace(turn, turn_id="turn-2"), "already recorded"),
        (replace(turn, turn_id="turn-2", input_id="answer-1"), "already recorded"),
    ]:
        with pytest.raises(ModelProtocolError, match=error):
            state.add_turn(snapshot)
    with pytest.raises(ValueError, match="does not belong"):
        state.add_turn(replace(turn, turn_id="turn-2", input_id="input-2", context_ids=("other",)))
    with pytest.raises(TypeError, match="TurnSnapshot"):
        state.add_turn(ANSWER)
    assert held(state) == ["input-1", "answer-1"]
    assert state.get_turn(turn.turn_id) is turn and state.get_turn("turn-2") is None


def correct(runtime: ParticipantRuntime, person: Participant, user_id: str) -> None:
    request = IdentityRequest(
        participant_id=person.participant_id,
        user_id=user_id,
        source=IdentitySource.AGENT,
        expected_revision=runtime.get(person.participant_id).identity_revision,
        reason="The user corrected their name",
    )
    assert runtime.bind_user(request) is IdentityOutcome.APPLIED


def test_records_are_whom_they_were_admitted_for_and_turns_whom_they_are_from(
    tmp_path: Path,
) -> None:
    runtime = participants(tmp_path)
    alice = runtime.join(user_id="alice", primary=True)
    state, turn = state_of(runtime), typed(runtime, "input-1", alice)
    basis = runtime.identity_basis(turn)
    state.add_turn(turn)
    state.add_messages([CALL], turn_id=turn.turn_id, identity_basis=basis)
    state.add_messages([ANSWER], turn_id=turn.turn_id)  # No basis: its Turn's participants.
    of_turn = runtime.of_turn

    for messages, users, unattributed in [
        ([turn], ["alice"], False),
        ([CALL], ["alice"], False),
        ([ANSWER], ["alice"], False),
        ([turn, CALL, ANSWER], ["alice"], False),
        ([replace(turn, modality=TurnInputModality.SYSTEM)], [], True),  # A notice: nobody's.
        (None, ["alice"], False),  # The context's participants.
    ]:
        identity = state.capture_identity(messages, of_turn=of_turn)
        assert [ref.key for ref in identity.owner_refs] == [
            "avatar:avatar",
            *(f"user:{user}" for user in users),
        ]
        assert [ref.key for ref in identity.participant_refs] == [
            "avatar:avatar",
            *(f"user:{user}" for user in users),
        ]
        assert identity.unattributed is unattributed
    with pytest.raises(ValueError, match="read from its Turns"):
        state.capture_identity([turn])

    # Once alice is corrected to bob, the record still holds the identity it was admitted with,
    # which is no longer the participant's: unattributed. Her Turn reads as bob now.
    correct(runtime, alice, "bob")
    state.sync_identity(runtime.session.snapshot())
    record = state.capture_identity([CALL], of_turn=of_turn)
    assert [ref.key for ref in record.owner_refs] == ["avatar:avatar"] and record.unattributed
    assert [ref.user_id for ref in record.participants] == ["alice"]
    now = state.capture_identity([turn], of_turn=of_turn)
    assert [ref.key for ref in now.owner_refs] == ["avatar:avatar", "user:bob"]
    assert not now.unattributed


def item(memory_id: str, revision: int, minute: int) -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        context=CONTEXT,
        owner_refs=[AVATAR],
        value=f"{memory_id} r{revision}",
        created_at=datetime(2026, 11, 22, 10, minute, tzinfo=UTC),
        revision=revision,
        memory_type=MemoryType.CONVERSATION,
    )


def test_memory_state_keeps_each_items_latest_revision_up_to_its_limit_and_forgets_discarded() -> (
    None
):
    memory = MemoryState(maximum_memory_num=2)
    kind = MemoryType.CONVERSATION
    memory.add(kind, [item("a", 2, 1), item("b", 1, 2)])
    # An older revision never replaces a newer one, but activates the item again.
    memory.add(kind, [item("a", 1, 1)])
    assert [m.value for m in memory.get(memory_type=kind)] == ["a r2", "b r1"]
    memory.add(kind, [item("c", 1, 3)])  # The limit keeps the latest activated: b goes.
    assert [m.value for m in memory.get(memory_type=kind)] == ["a r2", "c r1"]
    assert memory.get(memory_type=kind, context_id="other") == []

    memory.discard(["a", "unknown"])
    assert [m.value for m in memory.get(memory_type=kind)] == ["c r1"]
    assert memory.get(memory_type=MemoryType.ENV) == []
    with pytest.raises(ValueError, match="positive"):
        MemoryState(maximum_memory_num=0)
