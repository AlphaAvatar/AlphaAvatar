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
import os
from dataclasses import dataclass
from pathlib import Path

from alphaavatar.agents.utils.files.model_files import resolve_url_file


@dataclass(frozen=True, slots=True)
class SileroModelConfig:
    model: str
    version: str
    url: str
    sha256: str
    file_name: str
    sample_rate: int
    window_size_samples: int
    context_size_samples: int
    state_shape: tuple[int, int, int]
    inference_timeout_sec: float = 0.5

    @property
    def update_interval(self) -> float:
        return self.window_size_samples / self.sample_rate

    @property
    def state_size(self) -> int:
        size = 1
        for value in self.state_shape:
            size *= value
        return size


SILERO_MODEL_CONFIG = SileroModelConfig(
    model="silero-vad",
    version="v6.2.1",
    url=(
        "https://raw.githubusercontent.com/snakers4/silero-vad/"
        "v6.2.1/src/silero_vad/data/silero_vad.onnx"
    ),
    sha256="1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
    file_name="silero_vad_v6.2.1.onnx",
    sample_rate=16_000,
    window_size_samples=512,
    context_size_samples=64,
    state_shape=(2, 1, 128),
)


def resolve_silero_model_path() -> str:
    override = os.getenv("SILERO_VAD_MODEL_PATH")
    if override:
        path = Path(override).expanduser()
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Silero VAD model not found or empty: {path}")
        return str(path)
    config = SILERO_MODEL_CONFIG
    return str(
        resolve_url_file(
            namespace=("voice", "vad", "silero", config.version),
            filename=config.file_name,
            url=config.url,
            sha256=config.sha256,
        )
    )
