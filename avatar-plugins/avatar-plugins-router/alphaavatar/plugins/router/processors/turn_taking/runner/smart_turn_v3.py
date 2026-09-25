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

import numpy as np

from alphaavatar.agents.runtime.inference import InferenceRunner

from ..models.model_files import (
    SMART_TURN_V3_CONFIG,
    resolve_smart_turn_model_path,
)


class SmartTurnV3Runner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.router.turn_taking.smart_turn_v3"

    def initialize(self) -> None:
        import onnxruntime as ort
        from transformers import WhisperFeatureExtractor

        model_path = resolve_smart_turn_model_path()

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        available = ort.get_available_providers()
        providers = ["CPUExecutionProvider"] if "CPUExecutionProvider" in available else None

        if providers:
            self._session = ort.InferenceSession(
                model_path,
                providers=providers,
                sess_options=options,
            )
        else:
            self._session = ort.InferenceSession(
                model_path,
                sess_options=options,
            )

        self._feature_extractor = WhisperFeatureExtractor(
            chunk_length=int(SMART_TURN_V3_CONFIG.max_audio_sec)
        )

    def run(self, data: bytes) -> bytes:
        if not data:
            raise ValueError("Smart Turn request cannot be empty")
        if len(data) % 2:
            raise ValueError(f"Invalid PCM16 request size: bytes={len(data)}")

        config = SMART_TURN_V3_CONFIG

        audio = np.frombuffer(data, dtype="<i2").astype(np.float32)
        audio /= 32768.0

        if audio.size > config.max_samples:
            audio = audio[-config.max_samples :]

        inputs = self._feature_extractor(
            audio,
            sampling_rate=config.sample_rate,
            return_tensors="np",
            padding="max_length",
            max_length=config.max_samples,
            truncation=True,
            do_normalize=True,
        )

        features = inputs.input_features.squeeze(0).astype(
            np.float32,
            copy=False,
        )
        features = np.expand_dims(features, axis=0)

        outputs = self._session.run(
            None,
            {"input_features": features},
        )

        probability = float(
            np.clip(
                np.asarray(outputs[0]).reshape(-1)[0],
                0.0,
                1.0,
            )
        )

        return np.asarray([probability], dtype=np.float32).tobytes()
