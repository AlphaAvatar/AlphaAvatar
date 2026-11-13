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
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpeakerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    inference_queue_size: int = Field(default=1, ge=1)

    # How long a Turn's Context waits for its speech's speaker identity (a search took 1-8 ms).
    identity_wait_sec: float = Field(default=0.1, ge=0.0, allow_inf_nan=False)
    max_segments: int = Field(default=32, ge=1, le=256)
    # Participants whose speaker attributes are kept; the earliest kept goes first.
    max_speaker_caches: int = Field(default=64, ge=1, le=512)

    # Cosines of the campplus speaker vectors.
    track_match_threshold: float = Field(default=0.55, ge=0, le=1)
    track_match_margin: float = Field(default=0.0, ge=0, le=1)
    segment_consistency_threshold: float = Field(default=0.4, ge=0, le=1)

    # Speech shorter than short_segment_sec (by its VAD range) is not matched alone: it leads the
    # next segment of its source into that one's vector, a longer one at once and short ones once
    # together they reach short_merge_sec. A segment with its own subject drops it.
    short_segment_sec: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    short_merge_sec: float = Field(default=2.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _short_merge_covers_a_short_segment(self) -> "SpeakerConfig":
        if self.short_merge_sec < self.short_segment_sec:
            raise ValueError("short_merge_sec cannot be smaller than short_segment_sec")
        return self
