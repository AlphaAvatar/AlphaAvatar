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
from typing import TYPE_CHECKING

from alphaavatar.core.env.schemas.metadata import OutputMetadata
from alphaavatar.core.media.audio import AudioSampleFormat

from .identity import OutputIdentity
from .source import OutputSource

if TYPE_CHECKING:
    from alphaavatar.core.env.output import EnvOutput


@dataclass(frozen=True, slots=True)
class OutputAudioSummary:
    """A timeline-only receipt. It cannot be submitted as AUDIO_FRAME content."""

    identity: OutputIdentity
    source: OutputSource
    sample_rate: int
    num_channels: int
    samples_per_channel: int
    sample_format: AudioSampleFormat
    metadata: OutputMetadata

    @property
    def duration_sec(self) -> float:
        return self.samples_per_channel / self.sample_rate


@dataclass(frozen=True, slots=True)
class OutputTimelineEntry:
    event_id: str
    sequence: int
    session_id: str
    created_at: float
    monotonic_ns: int
    content: EnvOutput | OutputAudioSummary
