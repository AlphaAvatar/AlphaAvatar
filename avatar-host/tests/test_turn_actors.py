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
"""Whose Turn it is, on the configured chain: Engine names each segment's actor from the
association settled for that segment (Persona's part, done here by hand), never from the
device the speech came through nor from the session's primary participant."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from configured_chain import DEVICE, Chain, configured_chain, wait_until

from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSegmentRef

ALICE, BOB = PerceptionEntityRef("voice-alice"), PerceptionEntityRef("voice-bob")
# Each segment: the speaker its speech names, and the one its association settles on.
CASES = {
    "two-people": ((ALICE, ALICE), (BOB, BOB)),
    "known-and-unknown": ((ALICE, ALICE), (None, None)),
    "conflict": ((ALICE, BOB), (ALICE, ALICE)),  # Its speech names one, its association another
    "device-only": ((None, None), (None, None)),
}


@pytest.fixture
async def session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owned_addresses: set[object]
) -> AsyncIterator[Chain]:
    """Two segments the turn-taking model holds across, each transcribed in time."""
    answers = ((0.3, "What is two plus"), (0.3, "three?"))
    async with configured_chain(
        tmp_path, monkeypatch, owned_addresses, answers, frozenset({"segment-a"})
    ) as chain:
        yield chain


@pytest.mark.parametrize("case", CASES)
async def test_a_turns_actors_are_its_segments_associations_never_its_device(
    session: Chain, case: str
) -> None:
    runtime = session.execution.runtime
    participants = runtime.participants
    # Two people heard on the device, each a participant of their own besides its owner.
    people = {voice: participants.ensure_entity(session.speech, voice) for voice in (ALICE, BOB)}
    primary = participants.resolve(DEVICE, by_device=True)
    assert primary is not None and primary not in people.values()
    for segment_id, (named, associated) in zip(
        ("segment-a", "segment-b"), CASES[case], strict=True
    ):
        session.say(segment_id, named)
        segment = PerceptionSegmentRef(session.speech, segment_id)
        token = participants.observe_segment(segment)
        if associated is not None:
            participants.bind_segment(segment, associated, token=token)
    await wait_until(lambda: runtime.turn.latest is not None, "the turn never committed")

    turn = runtime.turn.latest
    expected = {
        "two-people": [people[ALICE].participant_id, people[BOB].participant_id],
        "known-and-unknown": [people[ALICE].participant_id, None],
        "conflict": [None, people[ALICE].participant_id],
        "device-only": [None, None],
    }[case]
    assert [actor.participant_id for actor in turn.actors] == expected
    assert {actor.user_id for actor in turn.actors if actor.participant_id is None} <= {None}
    assert primary.participant_id not in {actor.participant_id for actor in turn.actors}

    # An association settled after the admission changes nothing the Turn holds.
    late = PerceptionSegmentRef(session.speech, "segment-b")
    if case == "known-and-unknown":
        participants.bind_segment(late, BOB, token=participants.observe_segment(late))
    assert runtime.turn.get(turn.input_id).actors == turn.actors
