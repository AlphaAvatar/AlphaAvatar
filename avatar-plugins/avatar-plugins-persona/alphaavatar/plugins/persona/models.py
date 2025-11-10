# Copyright 2025 AlphaAvatar project
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
from typing import Any, Literal

from huggingface_hub import errors

from .log import logger


def download_from_hf_hub(repo_id: str, filename: str, **kwargs: Any) -> str:
    from huggingface_hub import hf_hub_download

    try:
        local_path = hf_hub_download(repo_id=repo_id, filename=filename, **kwargs)
    except (errors.LocalEntryNotFoundError, OSError):
        logger.error(
            f'Could not find file "{filename}". '
            "Make sure you have downloaded the model before running the agent. "
            "Use `python3 your_agent.py download-files` to download the model."
        )
        raise RuntimeError(
            "livekit-plugins-turn-detector initialization failed. "
            f'Could not find file "{filename}".'
        ) from None
    return local_path


class RunnerModelConfig:
    def __init__(
        self,
        hf_model: str,
        revision: str,
        file_name: str,
        sample_rate: int,
        window_size_samples: int,
        step_size_samples: int,
        embedding_dim: int | None = None,
    ) -> None:
        self.hf_model = hf_model
        self.revision = revision
        self.file_name = file_name
        self.sample_rate = sample_rate
        self.window_size_samples = window_size_samples
        self.step_size_samples = step_size_samples
        self.embedding_dim = embedding_dim


SpeakerModelType = Literal["eres2netv2", "w2v2l6"]


MODEL_CONFIG: dict[SpeakerModelType, RunnerModelConfig] = {
    "eres2netv2": RunnerModelConfig(
        hf_model="AlphaAvatar/plugins-persona",
        revision="speaker_vector_onnx",
        file_name="eres2netv2.onnx",
        sample_rate=16000,
        window_size_samples=int(3.0 * 16000),
        step_size_samples=int(1 * 16000),
        embedding_dim=192,
    ),
    "w2v2l6": RunnerModelConfig(
        hf_model="AlphaAvatar/plugins-persona",
        revision="speaker_attribute_onnx",
        file_name="w2v2l6.onnx",
        sample_rate=16000,
        window_size_samples=int(3.0 * 16000),
        step_size_samples=int(1 * 16000),
        embedding_dim=1024,
    ),
}
