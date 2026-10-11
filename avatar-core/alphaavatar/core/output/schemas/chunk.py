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

from dataclasses import dataclass, field
from uuid import uuid4

from ..enums import OutputTextMode
from ..enums.message_phase import OutputMessagePhase
from .validation import boolean, counter, identifier, identities, time_range


@dataclass(frozen=True, slots=True)
class OutputTextChunk:
    """Verbatim source text. Unlike normalized input TextPayload, whitespace is content."""

    text: str
    chunk_id: str = field(default_factory=lambda: uuid4().hex)
    mode: OutputTextMode = OutputTextMode.MIRROR
    is_final: bool = False
    replace_lane: bool = True
    phase: OutputMessagePhase | None = None
    content_index: int | None = None

    def __post_init__(self) -> None:
        if type(self.text) is not str or self.text == "":
            raise ValueError("Source text requires a nonempty verbatim string")
        identifier(self.chunk_id, "chunk_id")
        if type(self.mode) is not OutputTextMode:
            raise TypeError("Expected OutputTextMode")
        boolean(self.is_final, "is_final")
        boolean(self.replace_lane, "replace_lane")
        if self.phase is not None and type(self.phase) is not OutputMessagePhase:
            raise TypeError("Expected OutputMessagePhase or None")
        if self.content_index is not None:
            counter(self.content_index, "content_index")


@dataclass(frozen=True, slots=True)
class OutputTranscriptChunk:
    text: str
    chunk_id: str = field(default_factory=lambda: uuid4().hex)
    source_chunk_ids: tuple[str, ...] = ()
    alignment_id: str | None = None
    start_time_sec: float | None = None
    end_time_sec: float | None = None
    is_first: bool = False
    is_final: bool = False
    interrupted: bool = False
    timing_source: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("is_first", "is_final", "interrupted"):
            boolean(getattr(self, name), name)
        if type(self.text) is not str or (not self.text and not self.is_final):
            raise ValueError("Only a final transcript may have empty text")
        identifier(self.chunk_id, "chunk_id")
        identities(self.source_chunk_ids, "source_chunk_ids")
        for name in ("alignment_id", "timing_source", "reason"):
            identifier(getattr(self, name), name, optional=True)
        time_range(self.start_time_sec, self.end_time_sec)
        if self.alignment_id is not None and not self.source_chunk_ids:
            raise ValueError("Aligned transcript requires source chunks")
