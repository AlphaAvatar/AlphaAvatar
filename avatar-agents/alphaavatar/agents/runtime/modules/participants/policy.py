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

from alphaavatar.core.session import DefaultIdentityPolicy
from alphaavatar.core.session.schemas import AssociationRequest, SessionSnapshot


class PrimaryParticipantIdentityPolicy(DefaultIdentityPolicy):
    """Bootstrap one face and speaker for an unambiguous primary endpoint."""

    def select(self, request: AssociationRequest, *, snapshot: SessionSnapshot) -> str | None:
        primary = snapshot.primary_participant_id
        if (
            primary is None
            or primary not in snapshot.participants
            or request.kind not in {"face", "speaker"}
            or request.candidate_count != 1
            or request.endpoint_participant_id != primary
            or (primary, request.kind) in request.occupied_kinds
            or any(value != primary for value in request.peer_participant_ids)
        ):
            return None

        return primary
