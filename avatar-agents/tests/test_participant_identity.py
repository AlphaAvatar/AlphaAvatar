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
"""Participant, device and user identities with Turn history and captured-write ownership."""

from __future__ import annotations

from pathlib import Path

import pytest

from alphaavatar.agents.memory.schemas import MemoryContextRef, MemoryOwnerRef
from alphaavatar.agents.runtime.modules.participants import ParticipantRuntime
from alphaavatar.agents.runtime.modules.participants.schemas import ParticipantInput
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session import (
    IdentityOutcome,
    IdentityRequest,
    IdentitySource,
    Participant,
    SessionRuntime,
)
from alphaavatar.core.turn import TurnRuntime
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef, TurnSnapshot
from alphaavatar.plugins.memory.state import MemoryContextState


def participants(tmp_path: Path, **limits: int) -> ParticipantRuntime:
    session = SessionRuntime(session_id="session-1")
    perception = PerceptionRuntime(
        session_id="session-1",
        stream_maxlens=dict.fromkeys(PerceptionStreamKind, 64),
        clock=session.clock,
    )
    return ParticipantRuntime(
        session=session,
        workspace=WorkspacePaths.from_root(tmp_path / "workspace"),
        turn=TurnRuntime(perception=perception),
        **limits,
    )


def correct(
    runtime: ParticipantRuntime,
    participant: Participant,
    user_id: str | None,
    source: IdentitySource = IdentitySource.PERCEPTION,
) -> IdentityOutcome:
    return runtime.bind_user(
        IdentityRequest(
            participant_id=participant.participant_id,
            user_id=user_id,
            source=source,
            basis_sequence=participant.identity_sequence,
            reason=f"{source.value} evidence for {user_id}",
        )
    )


def commit(runtime: ParticipantRuntime, input_id: str, *people: Participant) -> TurnSnapshot:
    return runtime.turn.commit_input(
        input_id=input_id,
        modality=TurnInputModality.TEXT,
        text=f"text for {input_id}",
        actors=tuple(
            TurnEntityRef(
                kind="person",
                participant_id=person.participant_id,
                identity_sequence=person.identity_sequence,
                user_id=person.user_id,
            )
            for person in people
        ),
        context_ids=("context-1",),
    )


def test_device_participant_and_user_identifiers_stay_separate(tmp_path: Path) -> None:
    runtime = participants(tmp_path)
    owner = runtime.join(primary=True)
    runtime.bind_device("phone-1", owner.participant_id)
    assert len({"phone-1", owner.participant_id, owner.user_id}) == 3

    camera, face = PerceptionSourceRef("camera-1", 1), PerceptionEntityRef("face-b")
    guest = runtime.ensure_entity(camera, face)
    assert guest.participant_id != owner.participant_id
    assert guest.user_id not in {None, owner.user_id}
    # The device names its explicit submitter only; it never claims people seen through it.
    assert runtime.resolve("phone-1") is None
    assert runtime.resolve("phone-1", by_device=True) == owner
    assert runtime.resolve(source=camera, entity=face) == guest

    # Sharing a user binding never merges participants.
    twin = runtime.join(user_id=owner.user_id)
    assert twin.participant_id != owner.participant_id
    assert runtime.session.get_participant(user_id=owner.user_id) is None

    assert correct(runtime, owner, "user-a") is IdentityOutcome.APPLIED
    resolved = runtime.resolve("phone-1", by_device=True)
    assert (resolved.participant_id, resolved.user_id, resolved.identity_sequence) == (
        owner.participant_id,
        "user-a",
        1,
    )
    assert runtime.resolve(source=camera, entity=face) == guest
    assert runtime.user_path(resolved) == runtime.workspace.users.get("user-a")
    assert not (tmp_path / "workspace").exists()


def test_turn_history_keeps_its_accepted_identity_across_corrections(tmp_path: Path) -> None:
    runtime = participants(tmp_path)
    person = runtime.join(user_id="user-b", primary=True)
    turn = commit(runtime, "input-1", person)
    captured = runtime.identity_basis(turn)

    assert correct(runtime, person, "user-a") is IdentityOutcome.APPLIED
    assert correct(runtime, runtime.get(person.participant_id), "user-c", IdentitySource.AGENT) is (
        IdentityOutcome.APPLIED
    )

    assert runtime.turn.get("input-1") is turn
    assert (turn.actors[0].user_id, turn.actors[0].identity_sequence) == ("user-b", 0)
    projected = runtime.project_turn(turn).actors[0]
    assert (projected.participant_id, projected.user_id, projected.identity_sequence) == (
        person.participant_id,
        "user-c",
        2,
    )
    assert not runtime.identity_basis_is_current(captured)
    assert runtime.identity_basis_is_current(runtime.identity_basis(turn))

    # A captured write keeps its accepted target; the old snapshot cannot open new reads.
    assert runtime.user_path(person, current=False) == runtime.workspace.users.get("user-b")
    with pytest.raises(PermissionError):
        runtime.user_path(person)

    assert correct(runtime, runtime.get(person.participant_id), None) is IdentityOutcome.APPLIED
    with pytest.raises(PermissionError):
        runtime.user_path(runtime.get(person.participant_id))
    assert runtime.project_turn(turn).actors[0].user_id is None
    assert runtime.turn.get("input-1").actors == turn.actors


async def test_agent_identity_decisions_use_their_own_turn_and_version(tmp_path: Path) -> None:
    runtime = participants(tmp_path)
    person = runtime.join(user_id="user-a", primary=True)
    commit(runtime, "input-1", person)

    # C was never perceived or nominated; the Agent's reasoned decision is enough.
    applied = await runtime.invoke(
        ParticipantInput(user_id="user-c", reason="The user introduced themselves as C"),
        input_id="input-1",
    )
    assert applied == {
        "outcome": "applied",
        "participant_id": person.participant_id,
        "user_id": "user-c",
        "identity_sequence": 1,
    }
    event = runtime.session.identity_history(person.participant_id)[-1]
    assert (event.source, event.previous_user_id) == (IdentitySource.AGENT, "user-a")

    stale = await runtime.invoke(
        ParticipantInput(user_id="user-d", reason="Retrying an old decision", basis_sequence=0),
        input_id="input-1",
    )
    assert (stale["outcome"], stale["user_id"], stale["identity_sequence"]) == (
        "stale",
        "user-c",
        1,
    )
    reassessed = await runtime.invoke(
        ParticipantInput(user_id="user-d", reason="New evidence names D", basis_sequence=1),
        input_id="input-1",
    )
    assert (reassessed["outcome"], reassessed["user_id"]) == ("applied", "user-d")

    # Decisions bind to the calling execution's committed input, never the latest Turn.
    commit(runtime, "input-2", runtime.join(user_id="user-e"))
    for input_id in (None, "unknown-input"):
        with pytest.raises(ValueError):
            await runtime.invoke(
                ParticipantInput(user_id="user-x", reason="No committed input"), input_id=input_id
            )
    with pytest.raises(ValueError):
        await runtime.invoke(
            ParticipantInput(
                user_id="user-x",
                reason="Not an actor of this Turn",
                participant_id=runtime.session.get_participant(user_id="user-e").participant_id,
            ),
            input_id="input-1",
        )
    assert runtime.get(person.participant_id).user_id == "user-d"


def test_late_recognition_cannot_reopen_retired_or_evicted_associations(tmp_path: Path) -> None:
    runtime = participants(tmp_path, max_segments=1)
    microphone, voice = PerceptionSourceRef("microphone-1", 1), PerceptionEntityRef("speaker-1")
    person = runtime.ensure_entity(microphone, voice)
    segment = PerceptionSegmentRef(microphone, "segment-1")
    token = runtime.observe_segment(segment)
    assert runtime.bind_segment(segment, voice, token=token)
    late = IdentityRequest(
        participant_id=person.participant_id,
        user_id="user-x",
        source=IdentitySource.PERCEPTION,
        basis_sequence=person.identity_sequence,
        reason="Slow voiceprint match",
    )

    # A user correction leaves the established physical association intact.
    assert correct(runtime, person, "user-a", IdentitySource.MODEL) is IdentityOutcome.APPLIED
    assert runtime.resolve(segment=segment).user_id == "user-a"
    assert runtime.bind_user(late) is IdentityOutcome.STALE

    # Eviction retires the admission token even when the same segment reappears.
    runtime.observe_segment(PerceptionSegmentRef(microphone, "segment-2"))
    reopened = runtime.observe_segment(segment)
    assert reopened != token and not runtime.bind_segment(segment, voice, token=token)
    assert runtime.resolve(segment=segment) is None

    runtime.retire_source(microphone)
    assert not runtime.bind_segment(segment, voice, token=reopened)
    assert runtime.resolve(source=microphone, entity=voice) is None
    # Retiring media releases associations, not the participant or its accepted history.
    assert runtime.get(person.participant_id).user_id == "user-a"
    assert len(runtime.session.identity_history(person.participant_id)) == 2


def test_memory_batches_never_reassign_earlier_turns_to_a_corrected_user(tmp_path: Path) -> None:
    runtime = participants(tmp_path)
    person = runtime.join(user_id="user-b", primary=True)
    state = MemoryContextState(
        context=MemoryContextRef(
            episode_id="episode-1", context_id="context-1", session_id="session-1"
        ),
        provider_dir=tmp_path,
        owner_refs=[MemoryOwnerRef.avatar("avatar-1")],
        participants=(person,),
    )
    state.sync_identity(runtime.session.snapshot())
    spoken_by_b = commit(runtime, "input-1", person)
    state.add_turn(spoken_by_b)
    assert MemoryOwnerRef.user("user-b") in state.capture_identity([spoken_by_b]).owner_refs

    assert correct(runtime, person, "user-a") is IdentityOutcome.APPLIED
    state.sync_identity(runtime.session.snapshot())
    spoken_by_a = commit(runtime, "input-2", runtime.get(person.participant_id))
    state.add_turn(spoken_by_a)

    assert state.messages == [spoken_by_b, spoken_by_a]
    assert MemoryOwnerRef.user("user-a") not in state.capture_identity([spoken_by_b]).owner_refs
    assert MemoryOwnerRef.user("user-a") in state.capture_identity([spoken_by_a]).owner_refs
