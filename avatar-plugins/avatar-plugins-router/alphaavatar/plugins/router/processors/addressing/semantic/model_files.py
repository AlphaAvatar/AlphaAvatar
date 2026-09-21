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

import hashlib
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download

from alphaavatar.agents.utils.files import build_model_cache_dir


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(filename: str, expected_sha256: str, *, local_files_only: bool) -> str:
    config = SEMANTIC_ADDRESSING_CONFIG
    path = Path(
        hf_hub_download(
            repo_id=config.repo_id,
            filename=filename,
            revision=config.revision,
            cache_dir=build_model_cache_dir(
                "router",
                "addressing",
                "semantic_addressing",
            ),
            local_files_only=local_files_only,
        )
    )
    actual = _sha256(path)
    if actual != expected_sha256:
        raise RuntimeError(
            f"Semantic Addressing checksum mismatch for {filename}: "
            f"expected={expected_sha256}, actual={actual}"
        )
    return str(path)


def resolve_semantic_addressing_files(*, local_files_only: bool = False) -> tuple[str, str]:
    config = SEMANTIC_ADDRESSING_CONFIG
    return (
        _resolve(config.model_filename, config.model_sha256, local_files_only=local_files_only),
        _resolve(config.prompt_filename, config.prompt_sha256, local_files_only=local_files_only),
    )
