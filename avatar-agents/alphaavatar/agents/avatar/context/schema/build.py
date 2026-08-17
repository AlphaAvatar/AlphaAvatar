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
from dataclasses import dataclass

from alphaavatar.agents.avatar.vision import VisualSelection
from alphaavatar.agents.providers.schema import (
    ModelInput,
    ModelInputType,
)
from alphaavatar.core.perception import AlignedPerception


@dataclass(frozen=True, slots=True)
class ContextBuildRequest:
    base_input: ModelInput
    input_id: str
    alignment: AlignedPerception
    visual_selection: VisualSelection
    model_input_type: ModelInputType


@dataclass(frozen=True, slots=True)
class ContextBuildResult:
    model_input: ModelInput
