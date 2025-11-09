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
from typing import Literal


class RunnerModelConfig:
    def __init__(
        self,
        revision: str,
        sample_rate: int,
        window_size_samples: int,
        step_size_samples: int,
        embedding_dim: int | None = None,
    ) -> None:
        self.revision = revision
        self.sample_rate = sample_rate
        self.window_size_samples = window_size_samples
        self.step_size_samples = step_size_samples
        self.embedding_dim = embedding_dim


SpeakerModelType = Literal["eres2netv2", "w2v2l6"]


MODEL_CONFIG: dict[SpeakerModelType, RunnerModelConfig] = {
    "eres2netv2": RunnerModelConfig(
        revision="main",
        sample_rate=16000,
        window_size_samples=int(3.0 * 16000),
        step_size_samples=int(1 * 16000),
        embedding_dim=192,
    ),
    "w2v2l6": RunnerModelConfig(
        revision="main",
        sample_rate=16000,
        window_size_samples=int(3.0 * 16000),
        step_size_samples=int(1 * 16000),
        embedding_dim=1024,
    ),
}
