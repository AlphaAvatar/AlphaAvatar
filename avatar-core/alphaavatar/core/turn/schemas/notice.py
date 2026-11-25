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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TurnNotice:
    """An input condition carried by a Turn, optionally scoped to speech segments."""

    code: str
    segment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not 0 < len(self.code) <= 64:
            raise ValueError("Turn notice codes require 1..64 characters")
        if (
            not isinstance(self.segment_ids, Sequence)
            or isinstance(self.segment_ids, str | bytes)
            or any(not isinstance(value, str) or not value for value in self.segment_ids)
        ):
            raise ValueError("Turn notice segments require nonempty identities")
        object.__setattr__(self, "segment_ids", tuple(dict.fromkeys(self.segment_ids)))

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "segment_ids": list(self.segment_ids)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TurnNotice:
        return cls(code=data["code"], segment_ids=data.get("segment_ids", ()))


def normalize_turn_notices(notices: Sequence[TurnNotice]) -> tuple[TurnNotice, ...]:
    found: list[TurnNotice] = []
    for notice in notices:
        if not isinstance(notice, TurnNotice):
            raise TypeError("System notices must be TurnNotice values")
        if notice not in found:
            found.append(notice)
        if len(found) > 8:
            raise ValueError("A Turn can carry at most 8 distinct system notices")
    return tuple(found)
