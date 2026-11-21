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
device the speech came through nor from the session's primary participant; its log says whom
the Turn was admitted with and where each segment's association stood then."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from configured_chain import DEVICE, Chain, configured_chain, wait_until

from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSegmentRef
from alphaavatar.core.session import EntityKind

ALICE, BOB = PerceptionEntityRef("voice-alice"), PerceptionEntityRef("voice-bob")
# Each segment: the speaker its speech names, and the one its association settles on.
CASES = {
    "two-people": (ALICE, BOB),
    "known-and-unknown": (ALICE, None),
    "device-only": (None, None),
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
    session: Chain, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="alphaavatar.agents")
    runtime = session.execution.runtime
    participants = runtime.participants
    # Two people heard on the device, each a participant of their own besides its owner.
    people = {
        voice: participants.ensure_entity(session.speech, voice, kind=EntityKind.SPEAKER)
        for voice in (ALICE, BOB)
    }
    primary = participants.resolve(DEVICE, by_device=True)
    assert primary is not None and primary not in people.values()
    for segment_id, associated in zip(("segment-a", "segment-b"), CASES[case], strict=True):
        session.say(segment_id)
        segment = PerceptionSegmentRef(session.speech, segment_id)
        token = participants.observe_segment(segment)
        if associated is not None:
            participants.bind_segment(segment, associated, token=token)
    await wait_until(lambda: runtime.turn.latest is not None, "the turn never committed")

    turn = runtime.turn.latest
    expected = {
        "two-people": [people[ALICE].participant_id, people[BOB].participant_id],
        "known-and-unknown": [people[ALICE].participant_id, None],
        "device-only": [None, None],
    }[case]
    assert [actor.participant_id for actor in turn.actors] == expected
    assert {actor.user_id for actor in turn.actors if actor.participant_id is None} <= {None}
    assert primary.participant_id not in {actor.participant_id for actor in turn.actors}
    (line,) = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith(f"Turn participants turn_id={turn.turn_id} ")
    ]
    listed = ",".join(
        f"{actor.participant_id}/{actor.user_id}/r{actor.identity_revision}"
        if actor.participant_id
        else "unattributed"
        for actor in turn.actors
    )
    states = ",".join(
        f"{segment}:{'bound' if associated else 'pending'}"
        for segment, associated in zip(("segment-a", "segment-b"), CASES[case], strict=True)
    )
    assert line.endswith(f" participants={listed} segments={states}")

    # An association settled after the admission changes nothing the Turn holds.
    late = PerceptionSegmentRef(session.speech, "segment-b")
    if case == "known-and-unknown":
        participants.bind_segment(late, BOB, token=participants.observe_segment(late))
    assert runtime.turn.get(turn.input_id).actors == turn.actors
