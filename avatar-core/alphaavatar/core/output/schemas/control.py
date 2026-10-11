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

from ..enums import OutputControlType
from .identity import OutputIdentity
from .validation import boolean, counter, identifier


@dataclass(frozen=True, slots=True)
class OutputCompletionBarrier:
    last_audio_sequence: int
    last_alignment_sequence: int

    def __post_init__(self) -> None:
        counter(self.last_audio_sequence, "last_audio_sequence")
        counter(self.last_alignment_sequence, "last_alignment_sequence")


@dataclass(frozen=True, slots=True)
class OutputControl:
    """Runtime-produced facts. Targets are a snapshot, never selectors for future output."""

    type: OutputControlType
    reason: str
    targets: tuple[OutputIdentity, ...] = ()
    barrier: OutputCompletionBarrier | None = None
    affects_scope: bool = False

    def __post_init__(self) -> None:
        if type(self.type) is not OutputControlType:
            raise TypeError("Expected OutputControlType")
        identifier(self.reason, "reason")
        boolean(self.affects_scope, "affects_scope")
        if type(self.targets) is not tuple or any(
            type(target) is not OutputIdentity for target in self.targets
        ):
            raise TypeError("Interrupt targets must be an immutable identity tuple")
        if len({target.output_id for target in self.targets}) != len(self.targets):
            raise ValueError("Duplicate interrupt targets")
        if self.type == OutputControlType.INTERRUPT:
            if self.barrier is not None:
                raise ValueError("Interrupt is not a completion barrier")
        else:
            if self.targets or self.affects_scope:
                raise ValueError("Only interruption carries target sets")
            if self.type in (OutputControlType.AUDIO_COMPLETE, OutputControlType.COMPLETE):
                if type(self.barrier) is not OutputCompletionBarrier:
                    raise TypeError("Completion requires a typed barrier")
            elif self.barrier is not None:
                raise ValueError("Text completion is not an audio barrier")
