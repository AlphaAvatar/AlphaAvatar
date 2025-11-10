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
import base64
import json
import math
import os
from contextlib import ExitStack

import numpy as np
from huggingface_hub import errors
from livekit.agents.inference_runner import _InferenceRunner
from livekit.agents.utils import hw

from ..log import logger
from ..models import MODEL_CONFIG, SpeakerModelType, download_from_hf_hub

_resource_files = ExitStack()
atexit.register(_resource_files.close)


class SpeakerAttributeRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_persona_speaker_attribute"
    MODEL_TYPE: SpeakerModelType = "w2v2l6"

    def __init__(self):
        super().__init__()

    @staticmethod
    def _json_numpy(obj):
        """Make numpy objects JSON-serializable (ndarray -> base64 + meta; scalar -> .item())."""
        if isinstance(obj, np.ndarray):
            return {
                "__ndarray__": True,
                "dtype": str(obj.dtype),
                "shape": obj.shape,
                "base64": base64.b64encode(obj.tobytes()).decode("ascii"),
            }
        if isinstance(obj, np.generic):
            return obj.item()
        # Let json raise for anything else so we notice unexpected types
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    @staticmethod
    def decode(payload: bytes):
        """Helper to restore arrays on the receiving side."""

        def _restore(x):
            if isinstance(x, dict) and x.get("__ndarray__"):
                arr = np.frombuffer(base64.b64decode(x["base64"]), dtype=np.dtype(x["dtype"]))
                return arr.reshape(x["shape"])
            return x

        d = json.loads(payload.decode("utf-8"))
        return {k: _restore(v) for k, v in d.items()}

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
                logger.info("[SpeakerAttributeRunner] Running on CPU")
                self._session = ort.InferenceSession(
                    local_path_onnx, providers=["CPUExecutionProvider"], sess_options=opts
                )
            elif "CUDAExecutionProvider" in available:
                logger.info("[SpeakerAttributeRunner] Running on GPU (CUDA)")
                self._session = ort.InferenceSession(
                    local_path_onnx, providers=["CUDAExecutionProvider"], sess_options=opts
                )
            else:
                logger.info("[SpeakerAttributeRunner] Fallback: default provider")
                self._session = ort.InferenceSession(local_path_onnx, sess_options=opts)

            # Cache input/output names
            self._input_names = [i.name for i in self._session.get_inputs()]
            self._output_names = [o.name for o in self._session.get_outputs()]
            logger.info(f"[SpeakerAttributeRunner] Inputs: {self._input_names}")
            logger.info(f"[SpeakerAttributeRunner] Outputs: {self._output_names}")

        except (errors.LocalEntryNotFoundError, OSError):
            logger.error(
                f"[SpeakerAttributeRunner] Could not find model {MODEL_CONFIG[self.MODEL_TYPE].hf_model} with revision {MODEL_CONFIG[self.MODEL_TYPE].revision}. "
                "Make sure you have downloaded the model before running the agent. "
                "Use `python3 your_agent.py download-files` to download the models."
            )
            raise RuntimeError(
                "[SpeakerAttributeRunner] alphaavatar-plugins-persona initialization failed. "
                f"Could not find model {MODEL_CONFIG[self.MODEL_TYPE].hf_model} with revision {MODEL_CONFIG[self.MODEL_TYPE].revision}."
            ) from None

    def run(self, data: bytes) -> bytes:
        """
        Run speaker attribute inference on a raw float32 waveform buffer.

        Parameters
        ----------
        data : bytes
            Raw waveform bytes (float32-encoded).

        Returns
        -------
        bytes
            Serialized dictionary containing all outputs, or None on failure.
            Example structure before serialization:
            {
                "hidden_states": np.ndarray [1, 1024],
                "logits_age": np.ndarray [1, 1],
                "logits_gender": np.ndarray [1, 3],
            }
        """
        # Decode bytes to float32 waveform
        wav = np.frombuffer(data, dtype=np.float32).reshape(1, -1)
        ort_inputs = {self._input_names[0]: wav}

        # Run model and collect outputs
        ort_results = self._session.run(self._output_names, ort_inputs)

        # Combine outputs in a dict
        result_dict = dict(zip(self._output_names, ort_results, strict=False))

        # Serialize dict to bytes
        return json.dumps(result_dict, default=self._json_numpy).encode()
