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
import atexit
import importlib.resources
import math
import os
from contextlib import ExitStack

import numpy as np
import onnxruntime
from livekit.agents.inference_runner import _InferenceRunner
from livekit.agents.utils import hw

from ..fbank import FBank
from ..log import logger
from ..models import SpeakerVectoryModelType

_resource_files = ExitStack()
atexit.register(_resource_files.close)


class SpeakerVectorRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_perona_speaker_vector"
    MODEL_TYPE: SpeakerVectoryModelType = "eres2netv2"

    def __init__(self):
        super().__init__()

    def initialize(self) -> None:
        res = importlib.resources.files("alphaavatar.plugins.persona.resources") / "eres2netv2.onnx"
        ctx = importlib.resources.as_file(res)
        path = str(_resource_files.enter_context(ctx))

        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = max(1, min(math.ceil(hw.get_cpu_monitor().cpu_count()) // 2, 4))
        opts.inter_op_num_threads = 1
        opts.add_session_config_entry("session.dynamic_block_base", "4")
        available = onnxruntime.get_available_providers()

        if os.getenv("FORCE_CPU", "0") == "1" and "CPUExecutionProvider" in available:
            logger.info("[SpeakerVectorRunner] Running on CPU")
            self._session = onnxruntime.InferenceSession(
                path, providers=["CPUExecutionProvider"], sess_options=opts
            )
        elif "CUDAExecutionProvider" in available:
            logger.info("[SpeakerVectorRunner] Running on GPU (CUDA)")
            self._session = onnxruntime.InferenceSession(
                path, providers=["CUDAExecutionProvider"], sess_options=opts
            )
        else:
            logger.info("[SpeakerVectorRunner] Fallback: default provider")
            self._session = onnxruntime.InferenceSession(path, sess_options=opts)

        self._feature_extractor = FBank(80, sample_rate=16000, mean_nor=True)

    def run(self, data: bytes) -> bytes | None:
        wav_data = np.frombuffer(data, dtype=np.float32)
        ort_inputs = {"feature": self._feature_extractor(wav_data)}
        embedding: np.ndarray = self._session.run(None, ort_inputs)[0]  # type: ignore
        return embedding.tobytes()
