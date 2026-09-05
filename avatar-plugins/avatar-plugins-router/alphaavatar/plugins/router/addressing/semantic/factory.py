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
from alphaavatar.agents.router import SemanticAddressingModelBase
from alphaavatar.agents.runtime.inference import InferenceExecutor

from .model import Qwen3SemanticAddressingModel


def create_semantic_addressing_model(
    name: str,
    *,
    inference_executor: InferenceExecutor,
) -> SemanticAddressingModelBase:
    if name == "qwen3_0_6b_q8_0":
        return Qwen3SemanticAddressingModel(inference_executor=inference_executor)

    raise ValueError(f"Unsupported Semantic Addressing model: {name!r}")
