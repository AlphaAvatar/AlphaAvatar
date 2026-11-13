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

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .participant import Participant
from .validation import validate_identity, validate_sequence


@dataclass(frozen=True, slots=True)
class IdentityRef:
    """A participant's accepted identity version, without mutable profile data."""

    participant_id: str
    user_id: str | None
    identity_revision: int

    def __post_init__(self) -> None:
        validate_identity(self.participant_id, name="participant_id")
        if self.user_id is not None:
            validate_identity(self.user_id, name="user_id")
        validate_sequence(self.identity_revision, name="identity_revision")

    @classmethod
    def from_participant(cls, participant: Participant) -> IdentityRef:
        if not isinstance(participant, Participant):
            raise TypeError("Identity references require Participant")
        return cls(participant.participant_id, participant.user_id, participant.identity_revision)

    def matches(self, participant: Participant | None) -> bool:
        return (
            isinstance(participant, Participant)
            and participant.participant_id == self.participant_id
            and participant.user_id == self.user_id
            and participant.identity_revision == self.identity_revision
        )


@dataclass(frozen=True, slots=True)
class IdentityBasis:
    """Frozen identity evidence; an empty basis explicitly has no participant actors."""

    participants: tuple[IdentityRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.participants, tuple) or any(
            not isinstance(participant, IdentityRef) for participant in self.participants
        ):
            raise TypeError("Identity basis requires a tuple of IdentityRef")
        if len({ref.participant_id for ref in self.participants}) != len(self.participants):
            raise ValueError("Identity basis requires one version per participant")

    @classmethod
    def from_participants(cls, participants: Iterable[Participant]) -> IdentityBasis:
        references: dict[str, IdentityRef] = {}
        for participant in participants:
            reference = IdentityRef.from_participant(participant)
            if (
                reference.participant_id in references
                and references[reference.participant_id] != reference
            ):
                raise ValueError("Identity basis contains conflicting participant versions")
            references[reference.participant_id] = reference
        return cls(tuple(references.values()))

    def matches(self, get_identity: Callable[[str], Participant | None]) -> bool:
        return all(ref.matches(get_identity(ref.participant_id)) for ref in self.participants)
