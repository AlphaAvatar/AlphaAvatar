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


class RunnerSpeakerModelConfig:
    def __init__(
        self,
        hf_model: str,
        revision: str,
        file_name: str,
        sample_rate: int,
        window_size_samples: int,
        step_size_samples: int,
        embedding_dim: int | None = None,
        inference_timeout_sec: float = 1.0,
    ) -> None:
        self.hf_model = hf_model
        self.revision = revision
        self.file_name = file_name
        self.sample_rate = sample_rate
        self.window_size_samples = window_size_samples
        self.step_size_samples = step_size_samples
        self.embedding_dim = embedding_dim
        self.inference_timeout_sec = inference_timeout_sec


class RunnerFaceModelConfig:
    def __init__(
        self,
        *,
        hf_model: str | None = None,
        revision: str | None = None,
        model_name: str,
        root: str,
        allowed_modules: list[str],
        det_size: tuple[int, int],
        det_thresh: float,
        sample_interval_sec: float,
        min_face_size: int,
        jpeg_quality: int,
        embedding_dim: int,
        inference_timeout_sec: float,
    ) -> None:
        self.hf_model = hf_model
        self.revision = revision
        self.model_name = model_name
        self.root = root
        self.allowed_modules = allowed_modules
        self.det_size = det_size
        self.det_thresh = det_thresh
        self.sample_interval_sec = sample_interval_sec
        self.min_face_size = min_face_size
        self.jpeg_quality = jpeg_quality
        self.embedding_dim = embedding_dim
        self.inference_timeout_sec = inference_timeout_sec


SpeakerModelType = Literal["eres2netv2", "w2v2l6"]
FaceModelType = Literal["buffalo_l"]


SPEAKER_MODEL_CONFIG: dict[SpeakerModelType, RunnerSpeakerModelConfig] = {
    "eres2netv2": RunnerSpeakerModelConfig(
        hf_model="AlphaAvatar/plugins-persona",
        revision="speaker_vector_onnx",
        file_name="eres2netv2.onnx",
        sample_rate=16000,
        window_size_samples=int(3.0 * 16000),
        step_size_samples=int(1 * 16000),
        embedding_dim=192,
        inference_timeout_sec=2.0,
    ),
    "w2v2l6": RunnerSpeakerModelConfig(
        hf_model="AlphaAvatar/plugins-persona",
        revision="speaker_attribute_onnx",
        file_name="w2v2l6.onnx",
        sample_rate=16000,
        window_size_samples=int(3.0 * 16000),
        step_size_samples=int(1 * 16000),
        embedding_dim=1024,
        inference_timeout_sec=2.0,
    ),
}


FACE_MODEL_CONFIG: dict[FaceModelType, RunnerFaceModelConfig] = {
    "buffalo_l": RunnerFaceModelConfig(
        model_name="buffalo_l",
        root="~/.insightface",
        allowed_modules=["detection", "recognition", "genderage"],
        det_size=(640, 640),
        det_thresh=0.65,
        sample_interval_sec=0.75,
        min_face_size=48,
        jpeg_quality=85,
        embedding_dim=512,
        inference_timeout_sec=2.0,
    ),
}
