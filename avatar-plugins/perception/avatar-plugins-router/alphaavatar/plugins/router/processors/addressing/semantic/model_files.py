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

from alphaavatar.agents.utils.files.model_files import resolve_hf_file


@dataclass(frozen=True, slots=True)
class SemanticAddressingModelConfig:
    repo_id: str
    revision: str
    model_filename: str
    model_sha256: str
    prompt_filename: str
    prompt_sha256: str
    context_length: int
    label_0_token_id: int
    label_1_token_id: int
    threshold: float
    uncertainty_low: float
    uncertainty_high: float


SEMANTIC_ADDRESSING_CONFIG = SemanticAddressingModelConfig(
    repo_id="AlphaAvatar/router-semantic-addressing-qwen3-0.6b-gguf",
    revision="v1.0.1",
    model_filename="semantic-addressing-qwen3-0.6b-q8_0.gguf",
    model_sha256="01c657652e8f88a397c0a7bf540633b92d2c132fac1dcf88a47d0c86ce34843a",
    prompt_filename="prompt.txt",
    prompt_sha256="a7980c5a652999fb96ae9fa0ca26ff40aed93ccf2e27096193db6f7a8cb1de88",
    context_length=2048,
    label_0_token_id=15,
    label_1_token_id=16,
    threshold=0.302,
    uncertainty_low=0.1645,
    uncertainty_high=0.3755,
)


def resolve_semantic_addressing_files() -> tuple[str, str]:
    config = SEMANTIC_ADDRESSING_CONFIG
    namespace = ("router", "addressing", "semantic")
    model = resolve_hf_file(
        namespace=namespace,
        repo_id=config.repo_id,
        revision=config.revision,
        filename=config.model_filename,
        sha256=config.model_sha256,
    )
    prompt = resolve_hf_file(
        namespace=namespace,
        repo_id=config.repo_id,
        revision=config.revision,
        filename=config.prompt_filename,
        sha256=config.prompt_sha256,
    )
    return model, prompt
