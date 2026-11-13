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
"""Session identity acceptance: correctable bindings, version checks and retained history."""

from __future__ import annotations

import asyncio

from alphaavatar.core.session import (
    DefaultIdentityPolicy,
    IdentityOutcome,
    IdentityRequest,
    IdentitySource,
    SessionEventKind,
    SessionRuntime,
)

HANG_GUARD = 30


def request(
    participant_id: str, user_id: str | None, basis: int, source: IdentitySource, **fields: object
) -> IdentityRequest:
    fields.setdefault("reason", f"{source.value} evidence for {user_id}")
    return IdentityRequest(
        participant_id=participant_id,
        user_id=user_id,
        source=source,
        expected_revision=basis,
        **fields,
    )


def test_corrections_keep_the_participant_and_retain_every_accepted_version() -> None:
    session = SessionRuntime(session_id="session-1")
    joined = session.join(participant_id="participant-1", user_id="user-b")
    # Passive B->A, active A->C without C ever being perceived, a model correction, then unbind.
    corrections = [
        ("user-a", IdentitySource.PERCEPTION),
        ("user-c", IdentitySource.AGENT),
        ("user-b", IdentitySource.MODEL),
        (None, IdentitySource.AGENT),
    ]
    for basis, (user_id, source) in enumerate(corrections):
        outcome = session.request_identity(request("participant-1", user_id, basis, source))
        assert outcome is IdentityOutcome.APPLIED

    current = session.get_identity("participant-1")
    assert (current.participant_id, current.user_id, current.identity_revision) == (
        "participant-1",
        None,
        4,
    )
    assert (current.joined_at, joined.user_id) == (joined.joined_at, "user-b")
    history = session.identity_history("participant-1")
    assert [(event.kind, event.previous_user_id, event.source) for event in history] == [
        (SessionEventKind.JOINED, None, IdentitySource.DECLARED),
        (SessionEventKind.IDENTITY, "user-b", IdentitySource.PERCEPTION),
        (SessionEventKind.IDENTITY, "user-a", IdentitySource.AGENT),
        (SessionEventKind.IDENTITY, "user-c", IdentitySource.MODEL),
        (SessionEventKind.IDENTITY, "user-b", IdentitySource.AGENT),
    ]
    assert [session.get_identity("participant-1", n).user_id for n in range(5)] == [
        "user-b",
        "user-a",
        "user-c",
        "user-b",
        None,
    ]
    # Unbinding does not restore the initial user or allocate another one.
    assert session.primary_user_id is None


def test_late_or_unexplained_decisions_never_overwrite_the_current_binding() -> None:
    session = SessionRuntime()
    person = session.join(user_id="user-b")
    pid = person.participant_id
    late = request(pid, "user-x", 0, IdentitySource.PERCEPTION, score=0.91)
    assert session.request_identity(request(pid, "user-a", 0, IdentitySource.AGENT)) is (
        IdentityOutcome.APPLIED
    )
    sequence = session.events.latest_sequence

    assert session.request_identity(late) is IdentityOutcome.STALE
    assert session.request_identity(request(pid, "user-a", 1, IdentitySource.MODEL)) is (
        IdentityOutcome.UNCHANGED
    )
    unexplained = request(pid, "user-x", 1, IdentitySource.PERCEPTION, reason=None)
    assert session.request_identity(unexplained) is IdentityOutcome.REJECTED
    assert session.get_identity(pid).user_id == "user-a"
    assert session.events.latest_sequence == sequence
    assert len(session.identity_history(pid)) == 2


def test_a_decision_evaluated_against_an_outdated_session_snapshot_is_stale() -> None:
    class ConcurrentJoin(DefaultIdentityPolicy):
        def allow(self, request, *, participant, snapshot) -> bool:
            # Another component admits a participant while this decision is being evaluated.
            session.join(user_id="user-z")
            return True

    session = SessionRuntime(identity_policy=ConcurrentJoin())
    person = session.join(user_id="user-b")
    outcome = session.request_identity(
        request(person.participant_id, "user-a", 0, IdentitySource.PERCEPTION)
    )
    assert outcome is IdentityOutcome.STALE
    assert session.get_identity(person.participant_id) == person


def test_identity_history_outlives_the_bounded_stream_and_the_session() -> None:
    session = SessionRuntime(event_maxlen=2)
    pid = session.join(user_id="user-0").participant_id
    for basis in range(4):
        session.request_identity(request(pid, f"user-{basis + 1}", basis, IdentitySource.MODEL))

    read = session.events.read_pending(consumer_id="late-consumer")
    assert read.has_gap and read.missed_count == 3
    session.close()
    assert session.request_identity(request(pid, "user-x", 4, IdentitySource.AGENT)) is (
        IdentityOutcome.CLOSED
    )
    assert [event.participant.user_id for event in session.identity_history(pid)] == [
        f"user-{n}" for n in range(5)
    ]


async def test_identity_change_from_a_worker_thread_wakes_session_consumers() -> None:
    session = SessionRuntime()
    pid = session.join(user_id="user-b").participant_id
    stream = session.events
    stream.commit(consumer_id="watch", cursor_seq=stream.latest_sequence)
    waiting = asyncio.create_task(stream.wait_for_pending(consumer_id="watch"))
    await asyncio.sleep(0)
    assert not waiting.done()

    outcome = await asyncio.to_thread(
        session.request_identity, request(pid, "user-a", 0, IdentitySource.PERCEPTION)
    )
    async with asyncio.timeout(HANG_GUARD):
        assert outcome is IdentityOutcome.APPLIED and await waiting

    # A watcher that stops consuming is released rather than left waiting forever.
    stream.commit(consumer_id="watch", cursor_seq=stream.latest_sequence)
    waiting = asyncio.create_task(stream.wait_for_pending(consumer_id="watch"))
    await asyncio.sleep(0)
    stream.clear_consumer("watch")
    async with asyncio.timeout(HANG_GUARD):
        assert await waiting is False
