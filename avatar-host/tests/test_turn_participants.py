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
"""Whose Turn it is, on the configured chain: a Turn's participants are read from the
association settled for each of its segments (Persona's part, done here by hand), never from
the device the speech came through nor from the session's primary participant. Nothing is
fixed at admission: an association that settles later counts from then on, after its source
retires too. Admission's log says whom the Turn had then and where each association stood."""

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
async def test_a_turns_participants_are_its_segments_associations_never_its_device(
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
    admitted = participants.of_turn(turn)
    assert [entry.participant_id for entry in admitted] == expected
    assert {entry.user_id for entry in admitted if entry.participant_id is None} <= {None}
    assert primary.participant_id not in {entry.participant_id for entry in admitted}
    (line,) = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith(f"Turn participants turn_id={turn.turn_id} ")
    ]
    listed = ",".join(
        f"{entry.participant_id}/{entry.user_id}/r{entry.identity_revision}"
        if entry.participant_id
        else "unattributed"
        for entry in admitted
    )
    states = ",".join(
        f"{segment}:{'bound' if associated else 'pending'}"
        for segment, associated in zip(("segment-a", "segment-b"), CASES[case], strict=True)
    )
    assert line.endswith(f" participants={listed} segments={states}")

    # A segment still pending at admission, bound after it, counts from then on; and what
    # settled is still read once the source retires, as at a session's end.
    late = PerceptionSegmentRef(session.speech, "segment-b")
    if case == "known-and-unknown":
        participants.bind_segment(late, BOB, token=participants.observe_segment(late))
        expected = [people[ALICE].participant_id, people[BOB].participant_id]
    assert [entry.participant_id for entry in participants.of_turn(turn)] == expected
    participants.retire_source(session.speech)
    assert [entry.participant_id for entry in participants.of_turn(turn)] == expected
