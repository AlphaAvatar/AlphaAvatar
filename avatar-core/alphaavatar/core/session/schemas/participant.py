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

from alphaavatar.core.time import RuntimeTime

from .validation import validate_identity, validate_sequence


@dataclass(frozen=True, slots=True)
class Participant:
    participant_id: str
    user_id: str | None
    joined_at: RuntimeTime
    identity_sequence: int = 0
    timezone: str | None = None

    def __post_init__(self) -> None:
        validate_identity(self.participant_id, name="participant_id")
        if self.user_id is not None:
            validate_identity(self.user_id, name="user_id")
        if not isinstance(self.joined_at, RuntimeTime):
            raise TypeError("joined_at must be RuntimeTime")
        validate_sequence(self.identity_sequence, name="identity_sequence")
        if self.timezone is not None:
            validate_identity(self.timezone, name="timezone")
