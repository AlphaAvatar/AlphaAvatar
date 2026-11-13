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

import math
from dataclasses import dataclass

from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSourceRef

from ..enums import IdentitySource
from .validation import validate_identity, validate_sequence


@dataclass(frozen=True, slots=True)
class IdentityRequest:
    participant_id: str
    user_id: str | None
    source: IdentitySource
    expected_revision: int
    score: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        validate_identity(self.participant_id, name="participant_id")
        if self.user_id is not None:
            validate_identity(self.user_id, name="user_id")
        if not isinstance(self.source, IdentitySource):
            raise TypeError("source must be IdentitySource")
        validate_sequence(self.expected_revision, name="expected_revision")
        if self.score is not None and (
            isinstance(self.score, bool) or not math.isfinite(self.score)
        ):
            raise ValueError("score must be finite")
        if self.reason is not None and (
            not isinstance(self.reason, str) or not self.reason.strip() or len(self.reason) > 2048
        ):
            raise ValueError("reason must be nonempty text of at most 2048 characters")


@dataclass(frozen=True, slots=True)
class AssociationRequest:
    """Immutable physical-association evidence; identity policy supplies the decision."""

    source: PerceptionSourceRef
    entity: PerceptionEntityRef

    kind: str

    device_participant_id: str | None
    occupied_kinds: tuple[tuple[str, str], ...] = ()
    peer_participant_ids: frozenset[str] = frozenset()
    candidate_count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.source, PerceptionSourceRef) or not isinstance(
            self.entity, PerceptionEntityRef
        ):
            raise TypeError("Association requires explicit perception source and entity references")
        validate_identity(self.kind, name="kind")
        if self.device_participant_id is not None:
            validate_identity(self.device_participant_id, name="device_participant_id")
        if type(self.candidate_count) is not int or self.candidate_count < 1:
            raise ValueError("candidate_count must be a positive integer")
        object.__setattr__(
            self,
            "occupied_kinds",
            tuple(
                (
                    validate_identity(participant_id, name="participant_id"),
                    validate_identity(kind, name="kind"),
                )
                for participant_id, kind in self.occupied_kinds
            ),
        )
        object.__setattr__(
            self,
            "peer_participant_ids",
            frozenset(
                validate_identity(value, name="participant_id")
                for value in self.peer_participant_ids
            ),
        )
