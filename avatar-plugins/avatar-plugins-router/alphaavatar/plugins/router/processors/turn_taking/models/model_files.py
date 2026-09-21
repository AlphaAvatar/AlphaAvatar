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

from alphaavatar.agents.utils.files import build_model_cache_dir


@dataclass(frozen=True, slots=True)
class SmartTurnModelConfig:
    model: str
    version: str
    url: str
    sha256: str
    file_name: str

    sample_rate: int = 16_000
    num_channels: int = 1
    max_audio_sec: float = 8.0

    @property
    def max_samples(self) -> int:
        return int(self.sample_rate * self.max_audio_sec)


SMART_TURN_V3_CONFIG = SmartTurnModelConfig(
    model="smart-turn",
    version="v3.2-cpu",
    url=(
        "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/"
        "f766f81d3cfdf7737ac64aad813d91bbfd56bf93/"
        "smart-turn-v3.2-cpu.onnx"
    ),
    sha256="2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
    file_name="smart-turn-v3.2-cpu.onnx",
)


def _model_dir() -> Path:
    return build_model_cache_dir(
        "router",
        "turn_taking",
        "smart_turn",
        SMART_TURN_V3_CONFIG.version,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def resolve_smart_turn_model_path(*, local_files_only: bool) -> str:
    override = os.getenv("SMART_TURN_MODEL_PATH")

    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Smart Turn model not found: {path}")
        return str(path)

    config = SMART_TURN_V3_CONFIG
    model_dir = _model_dir()
    model_path = model_dir / config.file_name

    if model_path.is_file() and _sha256(model_path) == config.sha256:
        return str(model_path)

    if local_files_only:
        raise RuntimeError(
            f"Smart Turn model is unavailable at {model_path}. "
            "Run `alphaavatar download-files` first."
        )

    model_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = model_path.with_suffix(".onnx.part")

    try:
        with urllib.request.urlopen(config.url, timeout=60) as response:
            with temporary_path.open("wb") as output:
                shutil.copyfileobj(response, output)

        actual_hash = _sha256(temporary_path)
        if actual_hash != config.sha256:
            raise RuntimeError(
                "Smart Turn model checksum mismatch: "
                f"expected={config.sha256}, actual={actual_hash}"
            )

        temporary_path.replace(model_path)
        return str(model_path)

    finally:
        temporary_path.unlink(missing_ok=True)
