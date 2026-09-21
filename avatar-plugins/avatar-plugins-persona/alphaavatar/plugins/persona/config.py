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

from .processors.face import FaceConfig
from .processors.profiler import ProfilerConfig
from .processors.speaker import SpeakerConfig


class DefaultPersonaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiler: ProfilerConfig = Field(default_factory=ProfilerConfig)
    speaker: SpeakerConfig = Field(default_factory=SpeakerConfig)
    face: FaceConfig = Field(default_factory=FaceConfig)
