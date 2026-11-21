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

import logging
from collections import OrderedDict
from dataclasses import dataclass
from uuid import uuid4

from alphaavatar.agents.workspace import UserPath, WorkspacePaths
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import (
    DeviceId,
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
    SourceId,
)
from alphaavatar.core.session import Participant, SessionRuntime
from alphaavatar.core.session.enums import EntityKind, IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import (
    AssociationRequest,
    IdentityBasis,
    IdentityRequest,
    ParticipantId,
    validate_identity,
)
from alphaavatar.core.turn import TurnRuntime
from alphaavatar.core.turn.schemas import TurnEntityRef, TurnSnapshot

from ...capability import avatar_capability
from ...capability.enums import AvatarCapabilityName
from .binding import ParticipantBindings
from .schemas import ParticipantInput

logger = logging.getLogger(__name__)

# Inputs a person gives through a device of theirs, rather than speech an association names.
_DIRECT_INPUTS = frozenset((ObservationKind.TEXT_INPUT, ObservationKind.IMAGE_INPUT))


@dataclass(slots=True)
class _SegmentState:
    token: int
    segment: PerceptionSegmentRef
    observed_ns: int  # When its association was asked for, on the runtime clock
    entity: PerceptionEntityRef | None = None
    invalid: bool = False
    outcome: str | None = None  # How it settled, once: bound, unbound, invalid or released


@avatar_capability(
    name=AvatarCapabilityName.PARTICIPANT_IDENTITY,
    description=(
        "Identify or correct a participant speaking in this Turn using the conversation "
        "and available evidence. A user does not need a previous face or voice match. "
        "Explain the evidence in reason; use null user_id to clear a mistaken match. "
        "expected_revision defaults to the current accepted revision of this Turn's "
        "participant. For an explicit check, use the identity_revision returned by the "
        "previous result and reassess the evidence. "
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
        max_segments: int = 16384,
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

        self._active_participants: set[ParticipantId] = set(session.participants)

        # The entity kinds each participant has taken, and the participants seen on each bound
        # device: its own and at most one other.
        self._association_kinds: dict[ParticipantId, set[EntityKind]] = {}
        self._association_devices: dict[DeviceId, set[ParticipantId]] = {}

        # Each source's latest generation, and whether that generation is still current.
        self._generations: dict[SourceId, tuple[int, bool]] = {}

        # Each segment's association, kept for the session once settled: a Turn's participants
        # are read from it whenever they are needed, after the source retires too.
        self._segments: OrderedDict[PerceptionSegmentRef, _SegmentState] = OrderedDict()
        self._next_segment_token = 0

    @property
    def active_participant_ids(self) -> frozenset[ParticipantId]:
        return frozenset(self._active_participants)

    def _require_participant(self, participant_id: ParticipantId) -> Participant:
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

    def _settle(self, current: _SegmentState, outcome: str, reason: str | None = None) -> None:
        """Settle the association, once: the first time it is ready, and how, is what the trace
        keeps (bound, unbound, invalid or released). Ready is not recognized: a
        failure, an eviction or a retirement settles it too."""
        if current.outcome is not None:
            return
        current.outcome = outcome
        segment, perception = current.segment, self.turn.perception
        now_ns = perception.clock.now().monotonic_ns
        logger.info(
            "Speaker association settled segment_id=%s source_id=%s source_generation=%s "
            "outcome=%s reason=%s wait_ms=%.1f",
            segment.segment_id,
            segment.source.source_id,
            segment.source.source_generation,
            outcome,
            reason,
            (now_ns - current.observed_ns) / 1e6,
        )
        perception.input_trace.record(
            "participant.segment_ready",
            source_id=segment.source.source_id,
            source_generation=segment.source.source_generation,
            segment_id=segment.segment_id,
            outcome=outcome,
            reason=reason,
            start_time_ns=current.observed_ns,
            end_time_ns=now_ns,
        )

    def _drop_source(self, source: PerceptionSourceRef) -> None:
        # Entities outlive a source generation, and so do its settled associations: only the
        # segments still waiting for one are released.
        for segment, current in tuple(self._segments.items()):
            if segment.source == source and current.outcome is None:
                self._settle(self._segments.pop(segment), "released", "source_retired")

    def _admit_participant(self, participant_id: ParticipantId) -> None:
        if participant_id not in self._active_participants:
            if len(self._active_participants) >= self._max_participants:
                raise RuntimeError("Active participant capacity reached")
            self._active_participants.add(participant_id)

    def join(
        self,
        *,
        user_id: str | None = None,
        participant_id: ParticipantId | None = None,
        timezone: str | None = None,
        primary: bool = False,
    ) -> Participant:
        if self._closed:
            raise RuntimeError("ParticipantRuntime is closed")
        if len(self._active_participants) >= self._max_participants:
            raise RuntimeError("Active participant capacity reached")

        # Newcomers own a user namespace; recognition can correct this initial association later.
        participant = self.session.join(
            user_id=uuid4().hex if user_id is None else user_id,
            participant_id=participant_id,
            timezone=timezone,
            primary=primary,
            generated=user_id is None,
        )
        self._active_participants.add(participant.participant_id)
        return participant

    def get(self, participant_id: ParticipantId) -> Participant | None:
        return self.session.get_participant(participant_id=participant_id)

    def of_turn(self, snapshot: TurnSnapshot) -> tuple[TurnEntityRef, ...]:
        """The Turn's participants as they stand now, read from its input observations: each
        speech segment by the association settled for it, each direct input by its device's
        participant, and one anonymous entry for each input attributed to no one. Identities
        are the Session's current ones. Nothing is fixed when the Turn is admitted: an
        association that settles later counts from then on."""
        if any(event.session_id != self.session.session_id for event in snapshot.perception_events):
            raise ValueError("Turn participants are read only from this session's Turns")

        inputs = set(snapshot.input_observation_ids)
        found: dict[tuple[object, ...], TurnEntityRef] = {}
        for event in snapshot.perception_events:
            observation = event.observation
            if observation is None or observation.observation_id not in inputs:
                continue

            entity, participant_id = None, None
            if observation.segment is not None:
                # A shared microphone or the primary participant never names who spoke: the
                # segment's association, as Persona settled it, does.
                current = self._segments.get(observation.segment)
                if current is not None and not current.invalid:
                    entity = current.entity
                if entity is not None:
                    participant_id = self._bindings.get_entity(entity.entity_id)
            elif observation.kind in _DIRECT_INPUTS and observation.device_id is not None:
                participant_id = self._bindings.get_device(observation.device_id)

            participant = self.get(participant_id) if participant_id is not None else None
            if participant is not None:
                key: tuple[object, ...] = ("participant", participant.participant_id)
            elif entity is not None:
                key = ("entity", entity)
            else:
                # Each anonymous input once: a segment's speech and transcript are one input.
                key = ("unattributed", observation.segment or observation.observation_id)
            found.setdefault(
                key,
                TurnEntityRef(
                    kind="person",
                    participant_id=participant.participant_id if participant else None,
                    identity_revision=participant.identity_revision if participant else None,
                    user_id=participant.user_id if participant else None,
                    device_id=observation.device_id,
                    entity=entity,
                ),
            )
        return tuple(found.values())

    def identity_of(self, entry: TurnEntityRef) -> Participant | None:
        """The accepted identity a participant entry names: the Session's version at its
        revision, when it is that user's; None for an anonymous entry or any other."""
        if entry.participant_id is None or entry.identity_revision is None:
            return None
        participant = self.session.get_identity(entry.participant_id, entry.identity_revision)
        return (
            participant
            if participant is not None and participant.user_id == entry.user_id
            else None
        )

    def identity_basis(self, snapshot: TurnSnapshot) -> IdentityBasis:
        return IdentityBasis.from_participants(
            self._require_participant(entry.participant_id)
            for entry in self.of_turn(snapshot)
            if entry.participant_id is not None
        )

    def identity_basis_is_current(self, basis: IdentityBasis) -> bool:
        return not self._closed and basis.matches(self.get)

    def bind_device(self, device_id: DeviceId, participant_id: ParticipantId) -> None:
        self._require_participant(participant_id)
        self._bindings.check_device(device_id, participant_id)
        self._admit_participant(participant_id)
        self._bindings.bind_device(device_id, participant_id)

    def ensure_entity(
        self,
        source: PerceptionSourceRef,
        entity: PerceptionEntityRef,
        *,
        kind: EntityKind,
        participant_id: ParticipantId | None = None,
        device_id: DeviceId | None = None,
    ) -> Participant:
        """The entity's participant, on this source too: the one it is bound to, the one named,
        or, for an entity new to the session, the one identity policy selects or a newcomer."""
        if kind not in set(EntityKind):
            raise ValueError("Participant association kind must be face or speaker")
        if device_id is not None:
            validate_identity(device_id, name="device_id")

        participant = (
            self._require_participant(participant_id) if participant_id is not None else None
        )
        self._activate(source)
        self._bindings.check_entity(entity.entity_id, kind)
        existing = self.resolve(source=source, entity=entity)
        if (
            participant is not None
            and existing is not None
            and participant.participant_id != existing.participant_id
        ):
            raise ValueError("Entity is already bound to another participant")

        participant = participant or existing
        device_participant = self._bindings.get_device(device_id) if device_id is not None else None
        if participant is None and device_id is not None:
            participant = self.session.select_participant(
                AssociationRequest(
                    source=source,
                    entity=entity,
                    kind=kind,
                    device_participant_id=device_participant,
                    occupied_kinds=tuple(
                        (participant_id, value)
                        for participant_id, values in self._association_kinds.items()
                        for value in sorted(values)
                    ),
                    peer_participant_ids=frozenset(self._association_devices.get(device_id, ())),
                )
            )

        if participant is not None:
            # A second entity of a kind the participant has is refused before anything changes.
            self._bindings.check_entity(entity.entity_id, kind, participant.participant_id)

        participant = participant or self.join()
        self._admit_participant(participant.participant_id)
        self._bindings.bind_entity(entity.entity_id, participant.participant_id, kind)
        # Reserve before inference/I/O; expiration cannot transfer a slot to a stranger.
        self._association_kinds.setdefault(participant.participant_id, set()).add(kind)
        if device_id is not None and device_participant is not None:
            peers = self._association_devices.setdefault(device_id, set())
            # One competing-person witness preserves ambiguity without retaining every visit.
            if participant.participant_id == device_participant or not any(
                value != device_participant for value in peers
            ):
                peers.add(participant.participant_id)

        return participant

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
            current = self._segments[segment] = _SegmentState(
                self._next_segment_token, segment, self.turn.perception.clock.now().monotonic_ns
            )
            while len(self._segments) > self._max_segments:
                _, removed = self._segments.popitem(last=False)
                self._settle(removed, "released", "evicted")
        return current.token

    def finish_segment_resolution(
        self, segment: PerceptionSegmentRef, *, token: int, reason: str | None = None
    ) -> None:
        """The resolver is done with the segment; ``reason`` says why it found no entity."""
        current = self._segments.get(segment)
        if current is not None and current.token == token:
            outcome = (
                "invalid" if current.invalid else "unbound" if current.entity is None else "bound"
            )
            self._settle(current, outcome, None if outcome == "bound" else reason)

    def segment_association(self, segment: PerceptionSegmentRef) -> str:
        """Where the segment's association stands now: ``pending`` until it settles, then how
        it settled; ``unknown`` once released or never asked for."""
        current = self._segments.get(segment)
        if current is None:
            return "unknown"
        return "invalid" if current.invalid else current.outcome or "pending"

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
            self._settle(current, "invalid", "invalidated")

    def bind_segment(
        self, segment: PerceptionSegmentRef, entity: PerceptionEntityRef | None, *, token: int
    ) -> bool:
        # A late inference result cannot reopen an evicted or invalidated admission.
        if not self.segment_is_current(segment, token):
            return False

        current = self._segments[segment]
        if entity is not None and self._bindings.get_entity(entity.entity_id) is None:
            raise ValueError("Segment entity must be associated with a participant first")

        if entity is None or (
            current.entity is not None and current.entity.entity_id != entity.entity_id
        ):
            current.invalid = True
            self._settle(current, "invalid", "no_entity" if entity is None else "entity_conflict")
            return False

        current.entity = entity
        self._settle(current, "bound")
        return True

    def entity_for_segment(self, segment: PerceptionSegmentRef) -> PerceptionEntityRef | None:
        if not self.source_is_current(segment.source):
            return None

        current = self._segments.get(segment)
        return current.entity if current is not None and not current.invalid else None

    def resolve(
        self,
        device_id: DeviceId | None = None,
        *,
        source: PerceptionSourceRef | None = None,
        entity: PerceptionEntityRef | None = None,
        segment: PerceptionSegmentRef | None = None,
        by_device: bool = False,
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
            participant_id = self._bindings.get_entity(entity.entity_id)
        else:
            participant_id = self._bindings.get_device(device_id or "") if by_device else None

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
                participant.participant_id, None if current else participant.identity_revision
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

        entries = self.of_turn(snapshot)
        participant_id = request.participant_id
        if participant_id is None:
            participant_ids = {entry.participant_id for entry in entries}
            participant_id = next(iter(participant_ids)) if len(participant_ids) == 1 else None
            if participant_id is None:
                raise ValueError("Select a participant_id from the current Turn's participants")

        entry = next((entry for entry in entries if entry.participant_id == participant_id), None)
        if entry is None:
            raise ValueError("The participant is not one of the current Turn's participants")
        if self.identity_of(entry) is None:
            raise ValueError("The Turn participant must reference an accepted participant identity")

        # The execution supplies input_id separately from model arguments; binding uses one CAS.
        outcome = self.bind_user(
            IdentityRequest(
                participant_id=participant_id,
                user_id=request.user_id,
                source=IdentitySource.AGENT,
                expected_revision=(
                    entry.identity_revision
                    if request.expected_revision is None
                    else request.expected_revision
                ),
                reason=request.reason,
            )
        )
        current = self.get(participant_id)
        return {
            "outcome": outcome.value,
            "participant_id": participant_id,
            "user_id": current.user_id if current is not None else None,
            "identity_revision": current.identity_revision if current is not None else None,
        }

    def close(self) -> None:
        self._closed = True
        for current in self._segments.values():
            self._settle(current, "released", "closed")
        self._bindings.clear()
        self._active_participants.clear()
        self._association_kinds.clear()
        self._association_devices.clear()
        self._generations.clear()
        self._segments.clear()
