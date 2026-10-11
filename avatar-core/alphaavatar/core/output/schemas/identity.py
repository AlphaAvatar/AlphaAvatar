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

from ..enums import OutputLane
from .records import OutputScope
from .validation import identifier


@dataclass(frozen=True, slots=True)
class OutputIdentity:
    output_id: str
    lane: OutputLane
    scope: OutputScope

    def __post_init__(self) -> None:
        identifier(self.output_id, "output_id")
        if type(self.lane) is not OutputLane or type(self.scope) is not OutputScope:
            raise TypeError("Output identity requires typed lane and scope")
        identifier(self.scope.context_id, "context_id")
        identifier(self.scope.turn_id, "turn_id")
        identifier(self.scope.run_id, "run_id", optional=True)
        if self.lane == OutputLane.STATUS or self.scope.turn_id is None:
            raise ValueError("Content identity requires a content lane and turn")
