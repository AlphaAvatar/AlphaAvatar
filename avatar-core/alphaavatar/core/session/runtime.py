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
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from threading import RLock
from types import MappingProxyType
from typing import Protocol
from uuid import uuid4

from alphaavatar.core.time import RuntimeClock, RuntimeTime

from .enums import IdentityOutcome, SessionEventKind
from .schemas import IdentityRequest, Participant, SessionEvent, SessionSnapshot, validate_identity
from .stream import SessionStream


class IdentityPolicy(Protocol):
    """Synchronous, nonblocking identity decision; never performs I/O or grants data access."""

    def allow(
        self, request: IdentityRequest, *, participant: Participant, snapshot: SessionSnapshot
    ) -> bool: ...


class DefaultIdentityPolicy:
    """Accept versioned corrections from every source; data access has a separate owner."""

    def allow(
        self, request: IdentityRequest, *, participant: Participant, snapshot: SessionSnapshot
    ) -> bool:
        return True


class SessionRuntime:
    def __init__(
        self,
        *,
        session_id: str | None = None,
        clock: RuntimeClock | None = None,
        event_maxlen: int = 256,
        identity_policy: IdentityPolicy | None = None,
    ) -> None:
        self._session_id = validate_identity(
            uuid4().hex if session_id is None else session_id, name="session_id"
        )

        self._clock = clock if clock is not None else RuntimeClock()
        self._created_at = self._clock.now()
        self._lock = RLock()

        self._events = SessionStream(
            session_id=self._session_id, maxlen=event_maxlen, _lock=self._lock
        )

        # participant -> user
        self._participants: dict[str, Participant] = {}

        self._primary_participant_id: str | None = None
        self._closed = False
        self._identity_policy = (
            identity_policy if identity_policy is not None else DefaultIdentityPolicy()
        )

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def clock(self) -> RuntimeClock:
        return self._clock

    @property
    def created_at(self) -> RuntimeTime:
        return self._created_at

    @property
    def events(self) -> SessionStream:
        return self._events

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def participants(self) -> Mapping[str, Participant]:
        with self._lock:
            return MappingProxyType(dict(self._participants))

    @property
    def primary_participant_id(self) -> str | None:
        with self._lock:
            return self._primary_participant_id

    @property
    def primary_participant(self) -> Participant | None:
        with self._lock:
            return self._participants.get(self._primary_participant_id)

    @property
    def primary_user_id(self) -> str | None:
        participant = self.primary_participant
        return None if participant is None else participant.effective_user_id

    def _snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=self._session_id,
            sequence=self._events.latest_sequence,
            primary_participant_id=self._primary_participant_id,
            participants=self._participants,
            closed=self._closed,
            created_at=self._created_at,
        )

    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            return self._snapshot()

    def join(
        self,
        *,
        user_id: str,
        participant_id: str | None = None,
        timezone: str | None = None,
        primary: bool = False,
    ) -> Participant:
        participant = Participant(
            participant_id=uuid4().hex if participant_id is None else participant_id,
            user_id=user_id,
            joined_at=self._clock.now(),
            timezone=timezone,
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot join a closed session")

            if participant.participant_id in self._participants:
                raise ValueError(f"Participant already joined: {participant.participant_id}")

            self._participants[participant.participant_id] = participant
            if primary or self._primary_participant_id is None:
                self._primary_participant_id = participant.participant_id

            event = SessionEvent(
                session_id=self._session_id,
                sequence=self._events.latest_sequence + 1,
                kind=SessionEventKind.JOINED,
                at=participant.joined_at,
                participant=participant,
                primary_participant_id=self._primary_participant_id,
            )
            waiters = self._events._append(event)

        self._events._wake(waiters)
        return participant

    def get_participant(
        self, *, participant_id: str | None = None, user_id: str | None = None
    ) -> Participant | None:
        with self._lock:
            if participant_id is not None:
                participant = self._participants.get(participant_id)
                if participant is not None and (
                    user_id is None or participant.effective_user_id == user_id
                ):
                    return participant
                return None

            if user_id is None:
                return self._participants.get(self._primary_participant_id)

            matches = [
                participant
                for participant in self._participants.values()
                if participant.effective_user_id == user_id
            ]
            return matches[0] if len(matches) == 1 else None

    def request_identity(self, request: IdentityRequest) -> IdentityOutcome:
        if not isinstance(request, IdentityRequest):
            raise TypeError("request must be IdentityRequest")

        with self._lock:
            if self._closed:
                return IdentityOutcome.CLOSED
            participant = self._participants[request.participant_id]
            if participant.identity_sequence != request.basis_sequence:
                return IdentityOutcome.STALE
            snapshot = self._snapshot()

        # Policies receive immutable values and cannot hold the state lock across arbitrary work.
        allowed = self._identity_policy.allow(request, participant=participant, snapshot=snapshot)
        if not isinstance(allowed, bool):
            raise TypeError("IdentityPolicy.allow must return bool synchronously")

        with self._lock:
            if self._closed:
                return IdentityOutcome.CLOSED
            current = self._participants[request.participant_id]
            if (
                current.identity_sequence != request.basis_sequence
                or self._events.latest_sequence != snapshot.sequence
            ):
                return IdentityOutcome.STALE

            if not allowed:
                return IdentityOutcome.REJECTED

            if current.resolved_user_id == request.user_id:
                return IdentityOutcome.UNCHANGED

            updated = replace(
                current,
                resolved_user_id=request.user_id,
                identity_sequence=current.identity_sequence + 1,
            )
            event = SessionEvent(
                session_id=self._session_id,
                sequence=self._events.latest_sequence + 1,
                kind=SessionEventKind.IDENTITY,
                at=self._clock.now(),
                participant=updated,
                previous_user_id=current.effective_user_id,
                source=request.source,
                primary_participant_id=self._primary_participant_id,
            )
            self._participants[request.participant_id] = updated
            waiters = self._events._append(event)

        self._events._wake(waiters)
        return IdentityOutcome.APPLIED

    def close(self) -> SessionSnapshot:
        """End this session; this is neither a connection event nor a storage commit."""
        with self._lock:
            if self._closed:
                return self._snapshot()
            event = SessionEvent(
                session_id=self._session_id,
                sequence=self._events.latest_sequence + 1,
                kind=SessionEventKind.CLOSED,
                at=self._clock.now(),
                primary_participant_id=self._primary_participant_id,
            )
            self._closed = True
            waiters = self._events._append(event)
            snapshot = self._snapshot()

        self._events._wake(waiters)
        return snapshot
