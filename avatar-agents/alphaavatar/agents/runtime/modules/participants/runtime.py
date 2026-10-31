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

from collections import OrderedDict
from dataclasses import dataclass

from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.session import Participant, SessionRuntime
from alphaavatar.core.session.enums import IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import IdentityRequest
from alphaavatar.core.turn import TurnRuntime
from alphaavatar.core.workspace import UserPath, WorkspacePaths

from ...capability import avatar_capability
from ...capability.enums import AvatarCapabilityName
from .binding import ParticipantBindings
from .schemas import ParticipantInput


@dataclass(slots=True)
class _SegmentState:
    token: int
    entity: PerceptionEntityRef | None = None
    invalid: bool = False


@avatar_capability(
    name=AvatarCapabilityName.PARTICIPANT_IDENTITY,
    description=(
        "Identify or correct a participant speaking in this Turn using the conversation "
        "and available evidence. A user does not need a previous face or voice match. "
        "Explain the evidence in reason; use null user_id to clear a mistaken match. "
        "The default basis is the Turn's captured identity version. For a further correction, "
        "use the version returned by the previous result and reassess the evidence. "
        "Never blindly retry a stale decision. This tool returns identity state, not user data."
    ),
    input_schema=ParticipantInput,
)
class ParticipantRuntime:
    """Participant operations, observation links and accepted identity snapshots.

    Session owns identity state and events. This runtime performs no filesystem or model I/O;
    callers prepare a resolved UserPath explicitly, outside the realtime event loop.
    """

    def __init__(
        self,
        *,
        session: SessionRuntime,
        workspace: WorkspacePaths,
        turn: TurnRuntime,
        max_participants: int = 1024,
        max_segments: int = 1024,
        max_sources: int = 256,
    ) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (max_participants, max_segments, max_sources)
        ):
            raise ValueError("Participant runtime limits must be positive integers")
        if turn.perception.session_id != session.session_id:
            raise ValueError("ParticipantRuntime and TurnRuntime must belong to the same session")

        self.session = session
        self.workspace = workspace
        self.turn = turn

        self._closed = False
        self._max_participants = max_participants
        self._max_segments, self._max_sources = max_segments, max_sources

        self._bindings = ParticipantBindings(max_entities=max_participants, max_devices=max_sources)
        self._generations: dict[str, tuple[int, bool]] = {}
        self._segments: OrderedDict[PerceptionSegmentRef, _SegmentState] = OrderedDict()

        self._next_segment_token = 0

    def _require_participant(self, participant_id: str) -> Participant:
        if self._closed:
            raise RuntimeError("ParticipantRuntime is closed")
        participant = self.get(participant_id)
        if participant is None:
            raise KeyError(f"Participant has not joined this session: {participant_id}")
        return participant

    def _activate(self, source: PerceptionSourceRef) -> None:
        if self._closed:
            raise RuntimeError("ParticipantRuntime is closed")
        if not self.source_is_current(source):
            raise ValueError("Cannot bind a retired source generation")
        current = self._generations.get(source.source_id)
        if current is None and len(self._generations) >= self._max_sources:
            raise RuntimeError("Participant source capacity reached")
        if current is not None and source.source_generation > current[0]:
            self._drop_source(PerceptionSourceRef(source.source_id, current[0]))
        self._generations[source.source_id] = (source.source_generation, True)

    def _drop_source(self, source: PerceptionSourceRef) -> None:
        self._bindings.release_source(source)
        self._segments = OrderedDict(
            (key, value) for key, value in self._segments.items() if key.source != source
        )

    def join(
        self,
        *,
        user_id: str | None = None,
        participant_id: str | None = None,
        timezone: str | None = None,
        primary: bool = False,
    ) -> Participant:
        if self._closed:
            raise RuntimeError("ParticipantRuntime is closed")
        if len(self.session.participants) >= self._max_participants:
            raise RuntimeError("Session participant capacity reached")

        return self.session.join(
            user_id=user_id, participant_id=participant_id, timezone=timezone, primary=primary
        )

    def get(self, participant_id: str) -> Participant | None:
        return self.session.get_participant(participant_id=participant_id)

    def bind_device(self, device_id: str, participant_id: str) -> None:
        self._require_participant(participant_id)
        self._bindings.bind_device(device_id, participant_id)

    def ensure_entity(
        self,
        source: PerceptionSourceRef,
        entity: PerceptionEntityRef,
        *,
        participant_id: str | None = None,
    ) -> Participant:
        participant = (
            self._require_participant(participant_id) if participant_id is not None else None
        )
        self._activate(source)
        self._bindings.check_entity(source, entity.entity_id)
        participant = participant or self.resolve(source=source, entity=entity) or self.join()
        self._bindings.bind_entity(source, entity.entity_id, participant.participant_id)
        return participant

    def release_entity(self, source: PerceptionSourceRef, entity: PerceptionEntityRef) -> None:
        self._bindings.release_entity(source, entity.entity_id)
        for segment, current in self._segments.items():
            if (
                segment.source == source
                and current.entity is not None
                and current.entity.entity_id == entity.entity_id
            ):
                current.invalid = True

    def retire_source(self, source: PerceptionSourceRef) -> None:
        if self.source_is_current(source):
            self._activate(source)
            self._drop_source(source)
            self._generations[source.source_id] = (source.source_generation, False)

    def source_is_current(self, source: PerceptionSourceRef) -> bool:
        current = self._generations.get(source.source_id)
        return not self._closed and (
            current is None
            or source.source_generation > current[0]
            or (source.source_generation == current[0] and current[1])
        )

    def observe_source(self, source: PerceptionSourceRef) -> bool:
        if not self.source_is_current(source):
            return False
        self._activate(source)
        return True

    def observe_segment(self, segment: PerceptionSegmentRef) -> int:
        self._activate(segment.source)
        current = self._segments.get(segment)
        if current is None:
            self._next_segment_token += 1
            current = self._segments[segment] = _SegmentState(self._next_segment_token)
            while len(self._segments) > self._max_segments:
                self._segments.popitem(last=False)
        return current.token

    def segment_is_current(self, segment: PerceptionSegmentRef, token: int) -> bool:
        current = self._segments.get(segment)
        return (
            self.source_is_current(segment.source)
            and current is not None
            and current.token == token
            and not current.invalid
        )

    def invalidate_segment(self, segment: PerceptionSegmentRef) -> None:
        current = self._segments.get(segment)
        if current is not None:
            current.invalid = True

    def bind_segment(
        self, segment: PerceptionSegmentRef, entity: PerceptionEntityRef | None, *, token: int
    ) -> bool:
        # A late inference result cannot reopen an evicted or invalidated admission.
        if not self.segment_is_current(segment, token):
            return False

        current = self._segments[segment]
        if (
            entity is not None
            and self._bindings.get_entity(segment.source, entity.entity_id) is None
        ):
            raise ValueError("Segment entity must be associated with a participant first")

        if entity is None or (
            current.entity is not None and current.entity.entity_id != entity.entity_id
        ):
            current.invalid = True
            return False

        current.entity = entity
        return True

    def entity_for_segment(self, segment: PerceptionSegmentRef) -> PerceptionEntityRef | None:
        if not self.source_is_current(segment.source):
            return None

        current = self._segments.get(segment)
        return current.entity if current is not None and not current.invalid else None

    def resolve(
        self,
        device_id: str | None = None,
        *,
        source: PerceptionSourceRef | None = None,
        entity: PerceptionEntityRef | None = None,
        segment: PerceptionSegmentRef | None = None,
        endpoint: bool = False,
    ) -> Participant | None:
        if self._closed:
            return None

        if segment is not None:
            if source is not None and source != segment.source:
                return None

            source = segment.source
            associated = self.entity_for_segment(segment)
            if associated is None or (
                entity is not None and entity.entity_id != associated.entity_id
            ):
                return None

            entity = associated

        if source is not None and not self.source_is_current(source):
            return None

        if entity is not None:
            # Each observed person needs their own association, even on a shared device.
            participant_id = (
                self._bindings.get_entity(source, entity.entity_id) if source is not None else None
            )
        else:
            participant_id = self._bindings.get_device(device_id or "") if endpoint else None

        return self.get(participant_id) if participant_id is not None else None

    def bind_user(self, request: IdentityRequest) -> IdentityOutcome:
        # Decision components submit corrections; transport claims never call this implicitly.
        return IdentityOutcome.CLOSED if self._closed else self.session.request_identity(request)

    def accepts_identity(self, participant: Participant, *, current: bool = True) -> bool:
        """Check a current identity, or a captured write's previously accepted identity."""
        return (
            not self._closed
            and isinstance(participant, Participant)
            and self.session.get_identity(
                participant.participant_id, None if current else participant.identity_sequence
            )
            == participant
        )

    def user_path(self, participant: Participant, *, current: bool = True) -> UserPath:
        """Resolve the accepted subject; captured writes may retain an earlier accepted version."""
        if not self.accepts_identity(participant, current=current) or participant.user_id is None:
            raise PermissionError("User data requires an accepted participant identity")
        return self.workspace.users.get(participant.user_id)

    async def invoke(
        self, request: ParticipantInput, *, input_id: str | None = None
    ) -> dict[str, str | int | None]:
        snapshot = self.turn.get(input_id) if input_id is not None else None
        if snapshot is None:
            raise ValueError("Identity decisions require the calling execution's committed input")

        participant_id = request.participant_id
        if participant_id is None:
            participant_ids = {actor.participant_id for actor in snapshot.actors}
            participant_id = next(iter(participant_ids)) if len(participant_ids) == 1 else None
            if participant_id is None:
                raise ValueError("Select a participant_id from the current Turn's actors")

        actors = tuple(actor for actor in snapshot.actors if actor.participant_id == participant_id)
        if not actors or len({(actor.user_id, actor.identity_sequence) for actor in actors}) != 1:
            raise ValueError("The participant must have one identity in the current Turn")

        actor = actors[0]
        participant = self.session.get_identity(participant_id, actor.identity_sequence)
        if (
            actor.identity_sequence is None
            or participant is None
            or participant.user_id != actor.user_id
        ):
            raise ValueError("The Turn actor must reference an accepted participant identity")

        # The execution supplies input_id separately from model arguments; binding uses one CAS.
        outcome = self.bind_user(
            IdentityRequest(
                participant_id=participant_id,
                user_id=request.user_id,
                source=IdentitySource.AGENT,
                basis_sequence=(
                    actor.identity_sequence
                    if request.basis_sequence is None
                    else request.basis_sequence
                ),
                reason=request.reason,
            )
        )
        current = self.get(participant_id)
        return {
            "outcome": outcome.value,
            "participant_id": participant_id,
            "user_id": current.user_id if current is not None else None,
            "identity_sequence": current.identity_sequence if current is not None else None,
        }

    def close(self) -> None:
        self._closed = True
        self._bindings.clear()
        self._generations.clear()
        self._segments.clear()
