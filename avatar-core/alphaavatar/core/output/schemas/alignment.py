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

from .validation import boolean, counter, identifier, identities, time_range


@dataclass(frozen=True, slots=True)
class OutputTextAudioAlignment:
    """Audio-relative timing; estimates may be finalized without replacing source identity."""

    text: str
    alignment_id: str
    source_chunk_ids: tuple[str, ...]
    start_time_sec: float
    end_time_sec: float
    is_final: bool = False
    partial: bool = False
    timing_source: str = "synthesized_audio"
    revision: int = 0
    duration_final: bool = True

    def __post_init__(self) -> None:
        if type(self.text) is not str or not self.text:
            raise ValueError("Alignment requires verbatim source text")
        identifier(self.alignment_id, "alignment_id")
        identifier(self.timing_source, "timing_source")
        identities(self.source_chunk_ids, "source_chunk_ids", required=True)
        if self.start_time_sec is None or self.end_time_sec is None:
            raise ValueError("Alignment requires both time boundaries")
        time_range(self.start_time_sec, self.end_time_sec)
        boolean(self.is_final, "is_final")
        boolean(self.partial, "partial")
        boolean(self.duration_final, "duration_final")
        counter(self.revision, "revision")
        if self.partial and not self.duration_final:
            raise ValueError("Interrupted synthesis must seal its timing estimate")
