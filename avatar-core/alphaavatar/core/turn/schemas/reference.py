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

from alphaavatar.core.env.schemas import PerceptionEntityRef


@dataclass(frozen=True, slots=True)
class TurnEntityRef:
    kind: str | None = None
    participant_id: str | None = None
    identity_sequence: int | None = None
    user_id: str | None = None
    device_id: str | None = None
    entity: PerceptionEntityRef | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("kind", self.kind),
            ("participant_id", self.participant_id),
            ("user_id", self.user_id),
            ("device_id", self.device_id),
        ):
            if value == "":
                raise ValueError(f"{name} cannot be empty")
        if self.identity_sequence is not None and self.identity_sequence < 0:
            raise ValueError("identity_sequence cannot be negative")
        if self.identity_sequence is not None and self.participant_id is None:
            raise ValueError("Identity evidence requires an internal participant")
