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
import os
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
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


def _model_cache_dir() -> Path:
    root = os.getenv(
        "ALPHAAVATAR_MODEL_CACHE",
        "~/.cache/alphaavatar/models",
    )
    return Path(root).expanduser() / "voice" / "silero" / SILERO_MODEL_CONFIG.version


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def resolve_silero_model_path(*, local_files_only: bool) -> str:
    override = os.getenv("SILERO_VAD_MODEL_PATH")

    if override:
        path = Path(override).expanduser()

        if not path.is_file():
            raise FileNotFoundError(f"Silero VAD model not found: {path}")

        return str(path)

    config = SILERO_MODEL_CONFIG
    model_dir = _model_cache_dir()
    model_path = model_dir / config.file_name

    if model_path.is_file() and _sha256(model_path) == config.sha256:
        return str(model_path)

    if local_files_only:
        raise RuntimeError(
            f"Silero VAD model is unavailable at {model_path}. "
            "Run the `alphaavatar download-files` command first."
        )

    model_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = model_path.with_suffix(model_path.suffix + ".part")

    try:
        with urllib.request.urlopen(config.url, timeout=60) as response:
            with temporary_path.open("wb") as output:
                shutil.copyfileobj(response, output)

        actual_hash = _sha256(temporary_path)

        if actual_hash != config.sha256:
            raise RuntimeError(
                "Silero VAD model checksum mismatch: "
                f"expected={config.sha256}, actual={actual_hash}"
            )

        temporary_path.replace(model_path)
        return str(model_path)

    finally:
        temporary_path.unlink(missing_ok=True)
