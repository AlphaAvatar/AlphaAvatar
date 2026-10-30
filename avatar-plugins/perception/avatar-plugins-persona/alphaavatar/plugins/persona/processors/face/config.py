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
from pydantic import BaseModel, ConfigDict, Field


class FaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True

    max_faces: int = Field(default=16, ge=1, le=128)
    max_tracks: int = Field(default=128, ge=1, le=1024)
    track_ttl_sec: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    track_match_threshold: float = Field(default=0.65, gt=0, le=1)
    track_match_margin: float = Field(default=0.08, ge=0, le=1)
    identity_concurrency: int = Field(default=4, ge=1, le=16)
