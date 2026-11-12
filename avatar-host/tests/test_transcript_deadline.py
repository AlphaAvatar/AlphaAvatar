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
"""A transcript that misses its deadline, on the configured chain (KD-17), at turn taking's
default deadlines."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from configured_chain import Chain, configured_chain, wait_until

from alphaavatar.core.env.schemas import PerceptionEntityRef

WAIT, DEADLINE = 0.75, 3.0  # Turn taking's transcript wait and hard deadline, by default
LATE = 4.5  # A final past the deadline
NOTICE = '<system_notice code="voice.transcription_unavailable" current="true">'
REPEAT = "Briefly and naturally ask them to repeat what they said."
SUM, CARD, LOST = "What is two plus three?", "What color is the card?", "Words too late."


@pytest.fixture
async def session(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owned_addresses: set[object],
) -> AsyncIterator[Chain]:
    """The parameter is (answers, continues): how its transcription service answers, request
    by request, and the segments the turn-taking model holds."""
    async with configured_chain(tmp_path, monkeypatch, owned_addresses, *request.param) as chain:
        yield chain


@pytest.mark.parametrize(
    "session", [(((1.5, SUM), (LATE, LOST), (0.3, CARD)), frozenset())], indirect=True
)
async def test_a_transcript_past_its_deadline_commits_the_notice_and_its_late_final_joins_nothing(
    session: Chain,
) -> None:
    # Later than the transcript wait's point of observation, within the deadline: its words.
    said = time.monotonic()
    session.say("segment-1")
    await wait_until(lambda: session.completed() == 1, "the first turn never completed")
    assert SUM in session.current(0) and "system_notice" not in session.current(0)
    assert WAIT < session.model.sent[0] - said < DEADLINE

    # Past the deadline: the turn commits the STT's notice, so the answer can ask again.
    said = time.monotonic()
    session.say("segment-2")
    await wait_until(
        lambda: len(session.model.requests) == 2, "the untranscribed turn never committed"
    )
    assert NOTICE in session.current(1) and REPEAT in session.current(1)
    assert DEADLINE <= session.model.sent[1] - said < LATE  # At the deadline, not the final
    await wait_until(lambda: session.completed() == 2, "the notice's turn never completed")

    # The next utterance, its request queued behind the late one: that final arrives while the
    # next Turn waits for its own, and joins nothing.
    session.say("segment-3")
    await wait_until(lambda: session.completed() == 3, "the next turn never completed")
    assert CARD in session.current(2) and "system_notice" not in session.current(2)
    assert SUM in session.history(2) and NOTICE in session.history(2)
    assert not any(LOST in text for request in session.model.requests for _, text in request)
    (rejected,) = session.records("input.transcript_rejected")
    assert rejected["reason"] == "retired_segment"
    assert session.decided() == [("commit", 0), ("commit", 1), ("commit", 0)]


TWO_SEGMENTS = (((0.3, SUM), (LATE, LOST), (0.3, CARD)), frozenset({"segment-a"}))
VOICE, OTHER = PerceptionEntityRef("voice-1"), PerceptionEntityRef("voice-2")


@pytest.mark.parametrize("session", [TWO_SEGMENTS], indirect=True)
@pytest.mark.parametrize(
    "speakers", [(VOICE, VOICE), (None, None), (VOICE, OTHER)], ids=["one", "unnamed", "two"]
)
async def test_a_held_turn_keeps_the_words_it_has_and_marks_the_segment_it_lost(
    session: Chain, speakers: tuple[PerceptionEntityRef | None, ...]
) -> None:
    # The turn-taking model holds after the first segment; the second joins the same input, whoever
    # its speech names, and keeps its own deadline: the commit is due 3 s after it closed.
    first, second = speakers
    session.say("segment-a", first)
    said = time.monotonic()
    session.say("segment-b", second)
    await wait_until(lambda: session.completed() == 1, "the turn never completed")
    partial = '<unavailable_speech segment_id="segment-b" position="2" />'
    assert SUM in session.current(0) and partial in session.current(0)
    assert "Part of this input could not be understood." in session.current(0)
    assert DEADLINE <= session.model.sent[0] - said < LATE
    (pending,) = session.records("input.transcript_wait")
    assert pending["outcome"] == "pending"

    session.say("segment-c", first)
    await wait_until(lambda: session.completed() == 2, "the next turn never completed")
    assert CARD in session.current(1) and "system_notice" not in session.current(1)
    assert SUM in session.history(1) and partial in session.history(1)
    assert not any(LOST in text for request in session.model.requests for _, text in request)
    assert session.decided() == [("commit", 1), ("commit", 0)]
