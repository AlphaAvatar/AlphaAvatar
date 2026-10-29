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

from dataclasses import dataclass

from alphaavatar.agents.memory.schemas import MemoryOwnerRef, MemoryParticipantRef
from alphaavatar.core.session import Participant
from alphaavatar.core.turn.schemas import TurnEntityRef


@dataclass(frozen=True, slots=True)
class MemoryIdentitySnapshot:
    sequence: int
    participants: tuple[Participant, ...]
    owner_refs: tuple[MemoryOwnerRef, ...]
    participant_refs: tuple[MemoryParticipantRef, ...]
    actors: tuple[TurnEntityRef, ...] = ()
    unattributed: bool = False

    def evidence(self) -> dict:
        return {
            "sequence": self.sequence,
            "participants": [
                {
                    "participant_id": participant.participant_id,
                    "user_id": participant.user_id,
                    "identity_sequence": participant.identity_sequence,
                }
                for participant in self.participants
            ],
            "actors": [
                {
                    "participant_id": actor.participant_id,
                    "user_id": actor.user_id,
                    "identity_sequence": actor.identity_sequence,
                }
                for actor in self.actors
            ],
            "unattributed": self.unattributed,
        }
