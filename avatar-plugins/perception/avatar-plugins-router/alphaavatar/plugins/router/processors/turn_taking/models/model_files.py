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

from alphaavatar.agents.utils.files.model_files import resolve_hf_file


@dataclass(frozen=True, slots=True)
class SmartTurnModelConfig:
    model: str
    version: str
    repo_id: str
    revision: str
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
    repo_id="pipecat-ai/smart-turn-v3",
    revision="f766f81d3cfdf7737ac64aad813d91bbfd56bf93",
    sha256="2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
    file_name="smart-turn-v3.2-cpu.onnx",
)


def resolve_smart_turn_model_path() -> str:
    override = os.getenv("SMART_TURN_MODEL_PATH")
    if override:
        path = Path(override).expanduser()
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Smart Turn model not found or empty: {path}")
        return str(path)
    config = SMART_TURN_V3_CONFIG
    return resolve_hf_file(
        namespace=("router", "turn_taking", "smart_turn", config.version),
        repo_id=config.repo_id,
        revision=config.revision,
        filename=config.file_name,
        sha256=config.sha256,
    )
