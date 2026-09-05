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

from alphaavatar.agents.router import TurnTakingModelBase
from alphaavatar.agents.runtime.inference import InferenceExecutor

from .smart_turn_v3 import SmartTurnV3Model


def create_turn_taking_model(
    name: str,
    *,
    inference_executor: InferenceExecutor,
) -> TurnTakingModelBase:
    if name == "smart_turn_v3":
        return SmartTurnV3Model(
            inference_executor=inference_executor,
        )

    raise ValueError(f"Unsupported Turn-Taking model: {name!r}")
