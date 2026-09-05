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
from pathlib import Path
from typing import Any, Literal

from huggingface_hub import errors

from alphaavatar.agents.utils.files import build_model_cache_dir

from .log import logger


def _model_dir(*parts: str) -> Path:
    return build_model_cache_dir("persona", *parts)


def download_from_hf_hub(
    repo_id: str,
    filename: str,
    *,
    cache_dir: str | Path,
    **kwargs: Any,
) -> str:
    from huggingface_hub import hf_hub_download

    try:
        return hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            cache_dir=cache_dir,
            **kwargs,
        )
    except (errors.LocalEntryNotFoundError, OSError) as exc:
        logger.error(
            'Failed to load file "%s" from Hugging Face repository "%s": %s',
            filename,
            repo_id,
            exc,
        )
        raise RuntimeError(
            "Persona model initialization failed because "
            f'"{filename}" could not be loaded from "{repo_id}". '
            "Run `python3 your_agent.py download-files` before starting the agent."
        ) from exc


class RunnerSpeakerModelConfig:
    def __init__(
        self,
        *,
        hf_model: str,
        revision: str,
        file_name: str,
        cache_dir: str | Path,
        sample_rate: int,
        window_size_samples: int,
        step_size_samples: int,
        embedding_dim: int | None = None,
        inference_timeout_sec: float = 1.0,
    ) -> None:
        self.hf_model = hf_model
        self.revision = revision
        self.file_name = file_name
        self.cache_dir = cache_dir
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
        root: str | Path,
        allowed_modules: list[str],
        det_size: tuple[int, int],
        det_thresh: float,
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
        self.min_face_size = min_face_size
        self.jpeg_quality = jpeg_quality
        self.embedding_dim = embedding_dim
        self.inference_timeout_sec = inference_timeout_sec


SpeakerModelType = Literal["eres2netv2", "w2v2l6"]
FaceModelType = Literal["buffalo_l"]


SPEAKER_MODEL_CONFIG: dict[SpeakerModelType, RunnerSpeakerModelConfig] = {
    "eres2netv2": RunnerSpeakerModelConfig(
        hf_model="AlphaAvatar/persona-speaker-vector-onnx",
        revision="1899db09a40a60472681f07a189188517f515b4b",
        file_name="model.onnx",
        cache_dir=_model_dir("speaker", "vector"),
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
        cache_dir=_model_dir("speaker", "attribute"),
        sample_rate=16000,
        window_size_samples=3 * 16000,
        step_size_samples=16000,
        embedding_dim=1024,
        inference_timeout_sec=2.0,
    ),
}


FACE_MODEL_CONFIG: dict[FaceModelType, RunnerFaceModelConfig] = {
    "buffalo_l": RunnerFaceModelConfig(
        model_name="buffalo_l",
        root=_model_dir("insightface"),
        allowed_modules=["detection", "recognition", "genderage"],
        det_size=(640, 640),
        det_thresh=0.65,
        min_face_size=48,
        jpeg_quality=85,
        embedding_dim=512,
        inference_timeout_sec=2.0,
    ),
}
