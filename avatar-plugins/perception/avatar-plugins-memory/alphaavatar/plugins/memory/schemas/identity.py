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
from alphaavatar.core.turn.schemas import TurnEntityRef


@dataclass(frozen=True, slots=True)
class MemoryIdentitySnapshot:
    """Whom a batch is from, as it was captured: each participant its inputs name, by its
    identity then, and one anonymous entry for inputs attributed to no one."""

    sequence: int
    participants: tuple[TurnEntityRef, ...]
    owner_refs: tuple[MemoryOwnerRef, ...]
    participant_refs: tuple[MemoryParticipantRef, ...]
    unattributed: bool = False

    def evidence(self) -> dict:
        return {
            "sequence": self.sequence,
            "participants": [
                {
                    "participant_id": entry.participant_id,
                    "user_id": entry.user_id,
                    "identity_revision": entry.identity_revision,
                }
                for entry in self.participants
            ],
            "unattributed": self.unattributed,
        }
