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
from math import isfinite
from typing import TYPE_CHECKING

from .records import OutputScope
from .validation import counter, identifier

if TYPE_CHECKING:
    from alphaavatar.core.env.output import EnvOutput


@dataclass(frozen=True, slots=True)
class OutputEvent:
    """A publication receipt around a single domain object; journals have local sequences."""

    event_id: str
    sequence: int
    session_id: str
    created_at: float
    monotonic_ns: int
    output: EnvOutput

    def __post_init__(self) -> None:
        from alphaavatar.core.env.output import EnvOutput

        from .control import OutputControl

        payload = self.output.payload if type(self.output) is EnvOutput else None
        if isinstance(payload, OutputControl) and payload.barrier is not None:
            if (
                max(payload.barrier.last_audio_sequence, payload.barrier.last_alignment_sequence)
                >= self.sequence
            ):
                raise ValueError("Completion barrier must precede its publication sequence")
        identifier(self.event_id, "event_id")
        identifier(self.session_id, "session_id")
        counter(self.sequence, "sequence")
        counter(self.monotonic_ns, "monotonic_ns")
        if self.sequence == 0 or type(self.output) is not EnvOutput:
            raise ValueError("Publication requires a positive sequence and EnvOutput")
        if (
            type(self.created_at) not in (int, float)
            or not isfinite(self.created_at)
            or self.created_at < 0
        ):
            raise ValueError("Publication timestamp must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class OutputJournalEvent[T]:
    event_id: str
    sequence: int
    session_id: str
    created_at: float
    monotonic_ns: int
    key: str
    scope: OutputScope
    payload: T
    digest: str
    size_bytes: int
