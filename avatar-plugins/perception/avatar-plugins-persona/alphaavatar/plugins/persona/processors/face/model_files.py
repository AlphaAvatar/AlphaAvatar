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

from alphaavatar.agents.utils.files.model_files import resolve_zip_directory

FaceModelType = Literal["buffalo_l"]


@dataclass(frozen=True, slots=True)
class RunnerFaceModelConfig:
    model_name: str
    version: str
    url: str
    archive_size: int
    files: tuple[str, ...]
    allowed_modules: tuple[str, ...]
    det_size: tuple[int, int]
    det_thresh: float
    min_face_size: int
    jpeg_quality: int
    embedding_dim: int
    inference_timeout_sec: float


FACE_MODEL_CONFIG: dict[FaceModelType, RunnerFaceModelConfig] = {
    "buffalo_l": RunnerFaceModelConfig(
        model_name="buffalo_l",
        version="v0.7",
        url="https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
        archive_size=288621354,
        files=("det_10g.onnx", "w600k_r50.onnx", "genderage.onnx"),
        allowed_modules=("detection", "recognition", "genderage"),
        det_size=(640, 640),
        det_thresh=0.65,
        min_face_size=48,
        jpeg_quality=85,
        embedding_dim=512,
        inference_timeout_sec=2.0,
    ),
}


def resolve_face_model_root(model_type: FaceModelType) -> str:
    config = FACE_MODEL_CONFIG[model_type]
    model_dir = resolve_zip_directory(
        namespace=("persona", "face", config.model_name, config.version),
        name=config.model_name,
        url=config.url,
        files=config.files,
        size=config.archive_size,
    )
    return str(model_dir.parent.parent)
