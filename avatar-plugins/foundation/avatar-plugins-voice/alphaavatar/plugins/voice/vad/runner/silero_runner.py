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

from alphaavatar.agents.runtime.inference import InferenceRunner, RunnerProbe

from ..model_files import SILERO_MODEL_CONFIG, missing_silero_model, resolve_silero_model_path


class SileroVADRunner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.voice.vad.silero"
    # Context and recurrent state travel in each request; the session is read-only here.
    REPLICABLE = True

    @classmethod
    def probe(cls) -> RunnerProbe:
        config = SILERO_MODEL_CONFIG
        # A silent window, with the empty context and state a new stream starts from.
        size = config.window_size_samples + config.context_size_samples + config.state_size
        return RunnerProbe(
            model=f"Silero VAD {config.version}",
            request=np.zeros(size, dtype=np.float32).tobytes(),
            check=_check_silence,
            missing=lambda models_dir: missing_silero_model(models_dir=models_dir),
            audio_seconds=config.update_interval,
            device="cpu",  # Only ONNX Runtime's CPU provider is requested.
        )

    def initialize(self) -> None:
        import onnxruntime as ort

        model_path = resolve_silero_model_path(models_dir=self.launch.models_dir)

        options = ort.SessionOptions()
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

        available = ort.get_available_providers()
        providers = ["CPUExecutionProvider"] if "CPUExecutionProvider" in available else None

        if providers:
            self._session = ort.InferenceSession(
                model_path, providers=providers, sess_options=options
            )
        else:
            self._session = ort.InferenceSession(model_path, sess_options=options)

        self._sample_rate = np.array(SILERO_MODEL_CONFIG.sample_rate, dtype=np.int64)

    def run(self, data: bytes) -> bytes:
        config = SILERO_MODEL_CONFIG
        values = np.frombuffer(data, dtype=np.float32)

        request_size = config.window_size_samples + config.context_size_samples + config.state_size

        if values.size != request_size:
            raise ValueError(
                f"Invalid Silero request size: values={values.size}, expected={request_size}"
            )

        audio_end = config.window_size_samples
        context_end = audio_end + config.context_size_samples

        audio = values[:audio_end]
        context = values[audio_end:context_end]
        state = values[context_end:].reshape(config.state_shape)

        model_input = np.concatenate((context, audio)).reshape(1, -1)
        probability, next_state = self._session.run(
            None, {"input": model_input, "state": state, "sr": self._sample_rate}
        )

        response = np.empty(1 + config.state_size, dtype=np.float32)
        response[0] = float(np.asarray(probability).item())
        response[1:] = np.asarray(next_state, dtype=np.float32).reshape(-1)

        return response.tobytes()


def _check_silence(result: bytes | None) -> str:
    from ..silero import SileroVADOptions

    config = SILERO_MODEL_CONFIG
    values = np.frombuffer(result or b"", dtype=np.float32)
    if values.size != 1 + config.state_size or not np.isfinite(values).all():
        raise ValueError(f"expected {1 + config.state_size} finite values, got {values.size}")
    probability = float(values[0])
    if not 0 <= probability < SileroVADOptions().activation_threshold:
        raise ValueError(f"silence scored as speech: probability {probability:.3f}")
    return f"speech probability {probability:.3f} for silence; {config.state_size} state values"
