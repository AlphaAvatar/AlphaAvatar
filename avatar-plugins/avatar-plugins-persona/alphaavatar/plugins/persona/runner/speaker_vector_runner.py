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
import math
import os
from contextlib import ExitStack

import numpy as np
from huggingface_hub import errors
from livekit.agents.inference_runner import _InferenceRunner
from livekit.agents.utils import hw

from ..log import logger
from ..models import MODEL_CONFIG, SpeakerModelType, download_from_hf_hub
from ..utils.fbank import FBank

_resource_files = ExitStack()
atexit.register(_resource_files.close)


class SpeakerVectorRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_perona_speaker_vector"
    MODEL_TYPE: SpeakerModelType = "eres2netv2"

    def __init__(self):
        super().__init__()

    def initialize(self) -> None:
        """Initialize the ONNX Runtime session with dynamic provider selection."""
        import onnxruntime as ort

        try:
            local_path_onnx = download_from_hf_hub(
                MODEL_CONFIG[self.MODEL_TYPE].hf_model,
                MODEL_CONFIG[self.MODEL_TYPE].file_name,
                revision=MODEL_CONFIG[self.MODEL_TYPE].revision,
                local_files_only=True,
            )
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(
                1, min(math.ceil(hw.get_cpu_monitor().cpu_count()) // 2, 4)
            )
            opts.inter_op_num_threads = 1
            opts.add_session_config_entry("session.dynamic_block_base", "4")

            available = ort.get_available_providers()
            if os.getenv("FORCE_CPU", "0") == "1" and "CPUExecutionProvider" in available:
                logger.info("[SpeakerVectorRunner] Running on CPU")
                self._session = ort.InferenceSession(
                    local_path_onnx, providers=["CPUExecutionProvider"], sess_options=opts
                )
            elif "CUDAExecutionProvider" in available:
                logger.info("[SpeakerVectorRunner] Running on GPU (CUDA)")
                self._session = ort.InferenceSession(
                    local_path_onnx, providers=["CUDAExecutionProvider"], sess_options=opts
                )
            else:
                logger.info("[SpeakerVectorRunner] Fallback: default provider")
                self._session = ort.InferenceSession(local_path_onnx, sess_options=opts)

            self._feature_extractor = FBank(80, sample_rate=16000, mean_nor=True)

            # Cache input/output names
            self._input_names = [i.name for i in self._session.get_inputs()]
            self._output_names = [o.name for o in self._session.get_outputs()]
            logger.info(f"[SpeakerVectorRunner] Inputs: {self._input_names}")
            logger.info(f"[SpeakerVectorRunner] Outputs: {self._output_names}")

        except (errors.LocalEntryNotFoundError, OSError):
            logger.error(
                f"[SpeakerVectorRunner] Could not find model {MODEL_CONFIG[self.MODEL_TYPE].hf_model} with revision {MODEL_CONFIG[self.MODEL_TYPE].revision}. "
                "Make sure you have downloaded the model before running the agent. "
                "Use `python3 your_agent.py download-files` to download the models."
            )
            raise RuntimeError(
                "[SpeakerVectorRunner] alphaavatar-plugins-persona initialization failed. "
                f"Could not find model {MODEL_CONFIG[self.MODEL_TYPE].hf_model} with revision {MODEL_CONFIG[self.MODEL_TYPE].revision}."
            ) from None

    def run(self, data: bytes) -> bytes:
        wav_data = np.frombuffer(data, dtype=np.float32)
        ort_inputs = {"feature": self._feature_extractor(wav_data)}
        embedding: np.ndarray = self._session.run(None, ort_inputs)[0]  # type: ignore
        return embedding.tobytes()
