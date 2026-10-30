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

import math
import os

import numpy as np

from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.runtime.inference.cpu import available_cpu_count

from ...log import logger
from .model_files import SpeakerModelType, resolve_speaker_model_path


class SpeakerVectorRunner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.persona.speaker.vector"
    MODEL_TYPE: SpeakerModelType = "eres2netv2"

    def initialize(self) -> None:
        import onnxruntime as ort

        from .fbank import FBank

        path = resolve_speaker_model_path(self.MODEL_TYPE, models_dir=self.launch.models_dir)
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(math.ceil(available_cpu_count()) // 2, 4))
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.dynamic_block_base", "4")
        available = ort.get_available_providers()
        if os.getenv("FORCE_CPU", "0") == "1":
            if "CPUExecutionProvider" not in available:
                raise RuntimeError("FORCE_CPU requires the ONNX CPU execution provider")
            providers = ["CPUExecutionProvider"]
        elif "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider"]
        else:
            providers = available

        self._session = ort.InferenceSession(path, providers=providers, sess_options=options)
        self._input_names = [item.name for item in self._session.get_inputs()]
        self._output_names = [item.name for item in self._session.get_outputs()]
        logger.info(
            "%s ready providers=%s threads=%d",
            type(self).__name__,
            providers,
            options.intra_op_num_threads,
        )
        self._feature_extractor = FBank(80, sample_rate=16000, mean_nor=True)

    def run(self, data: bytes) -> bytes:
        waveform = np.frombuffer(data, dtype=np.float32)
        if not waveform.size or not np.isfinite(waveform).all():
            raise ValueError("Speaker waveform must contain finite float32 samples")
        inputs = {"feature": self._feature_extractor(waveform)}
        embedding = self._session.run(None, inputs)[0]
        return embedding.tobytes()
