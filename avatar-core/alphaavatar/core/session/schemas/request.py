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

from ..enums import IdentitySource
from .validation import validate_identity, validate_sequence


@dataclass(frozen=True, slots=True)
class IdentityRequest:
    participant_id: str
    user_id: str | None
    source: IdentitySource
    basis_sequence: int
    score: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        validate_identity(self.participant_id, name="participant_id")
        if self.user_id is not None:
            validate_identity(self.user_id, name="user_id")
        if not isinstance(self.source, IdentitySource):
            raise TypeError("source must be IdentitySource")
        validate_sequence(self.basis_sequence, name="basis_sequence")
        if self.score is not None and (
            isinstance(self.score, bool) or not math.isfinite(self.score)
        ):
            raise ValueError("score must be finite")
        if self.reason is not None and (
            not isinstance(self.reason, str) or not self.reason.strip() or len(self.reason) > 2048
        ):
            raise ValueError("reason must be nonempty text of at most 2048 characters")
