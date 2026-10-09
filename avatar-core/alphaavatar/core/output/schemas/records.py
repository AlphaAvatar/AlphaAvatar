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
from typing import Generic, TypeVar

from ..enums import ExecutionSignalKind

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class OutputScope:
    context_id: str
    turn_id: str | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("context_id", "turn_id", "run_id"):
            value = getattr(self, name)
            if value is None and name != "context_id":
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Output {name} must be a nonempty string")


@dataclass(frozen=True, slots=True)
class OutputRecordBatch(Generic[T]):
    """Immutable producer-owned records, not user delivery or durable persistence.

    digest identifies the frozen content; size_bytes accounts for retained payload.
    The producer owns payload validation. Core never imports its record classes.
    """

    batch_id: str
    source: str
    schema: str
    scope: OutputScope
    items: tuple[T, ...]
    digest: str
    size_bytes: int

    def __post_init__(self) -> None:
        for value in (self.batch_id, self.source, self.schema):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Record batches require identity, source and schema")
        if not isinstance(self.scope, OutputScope):
            raise TypeError("Expected OutputScope")
        if not isinstance(self.items, tuple) or not self.items:
            raise ValueError("Record batches require a nonempty tuple")
        if (
            not isinstance(self.digest, str)
            or len(self.digest) != 64
            or any(c not in "0123456789abcdef" for c in self.digest)
        ):
            raise ValueError("Record digest must be SHA-256 hex")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise ValueError("Record size_bytes must be positive")


@dataclass(frozen=True, slots=True)
class OutputExecutionSignal:
    """Execution facts only. Presentation and narration belong to consumers."""

    scope: OutputScope
    kind: ExecutionSignalKind
    state: str
    model_step: int = 0
    tool_round: int = 0
    request_id: str | None = None
    call_id: str | None = None
    tool_name: str | None = None
    outcome: str | None = None
    executed: bool | None = None
    reason: str | None = None
    commentary_output_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.scope, OutputScope) or not isinstance(
            self.kind, ExecutionSignalKind
        ):
            raise TypeError("Execution signals require typed scope and kind")
        if not isinstance(self.state, str) or not self.state:
            raise ValueError("Execution state must be nonempty")
        if any(type(n) is not int or n < 0 for n in (self.model_step, self.tool_round)):
            raise ValueError("Execution counters must be nonnegative integers")
        if self.executed is not None and type(self.executed) is not bool:
            raise TypeError("executed must be bool or None")
        if not isinstance(self.commentary_output_ids, tuple):
            raise TypeError("commentary_output_ids must be a tuple")
        strings = (
            self.state,
            self.request_id,
            self.call_id,
            self.tool_name,
            self.outcome,
            self.reason,
            *self.commentary_output_ids,
        )
        if any(v is not None and (not isinstance(v, str) or len(v) > 2048) for v in strings):
            raise ValueError("Execution signal fields must be bounded strings")
        if len(self.commentary_output_ids) > 64:
            raise ValueError("Too many commentary references")
