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
from typing import Literal

from alphaavatar.agents.utils.files.model_files import resolve_hf_file

SpeakerModelType = Literal["eres2netv2", "w2v2l6"]


@dataclass(frozen=True, slots=True)
class RunnerSpeakerModelConfig:
    hf_model: str
    revision: str
    file_name: str
    cache_parts: tuple[str, ...]
    sample_rate: int
    window_size_samples: int
    step_size_samples: int
    embedding_dim: int | None = None
    inference_timeout_sec: float = 1.0


SPEAKER_MODEL_CONFIG: dict[SpeakerModelType, RunnerSpeakerModelConfig] = {
    "eres2netv2": RunnerSpeakerModelConfig(
        hf_model="AlphaAvatar/persona-speaker-vector-onnx",
        revision="1899db09a40a60472681f07a189188517f515b4b",
        file_name="model.onnx",
        cache_parts=("persona", "speaker", "vector"),
        sample_rate=16000,
        window_size_samples=3 * 16000,
        step_size_samples=16000,
        embedding_dim=192,
        inference_timeout_sec=2.0,
    ),
    "w2v2l6": RunnerSpeakerModelConfig(
        hf_model="AlphaAvatar/persona-speaker-attribute-onnx",
        revision="3174195619187307495d5fa782a87dac86c5ddec",
        file_name="model.onnx",
        cache_parts=("persona", "speaker", "attribute"),
        sample_rate=16000,
        window_size_samples=3 * 16000,
        step_size_samples=16000,
        embedding_dim=1024,
        inference_timeout_sec=2.0,
    ),
}


def resolve_speaker_model_path(model_type: SpeakerModelType) -> str:
    config = SPEAKER_MODEL_CONFIG[model_type]
    return resolve_hf_file(
        namespace=config.cache_parts,
        repo_id=config.hf_model,
        revision=config.revision,
        filename=config.file_name,
    )
