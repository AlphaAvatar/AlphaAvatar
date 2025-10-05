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
import json
import math
import os
from contextlib import ExitStack

import onnxruntime
from livekit.agents.inference_runner import _InferenceRunner
from livekit.agents.utils import hw

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

        if (
            os.getenv("FORCE_CPU", 1)
            and "CPUExecutionProvider" in onnxruntime.get_available_providers()
        ):
            self._session = onnxruntime.InferenceSession(
                path, providers=["CPUExecutionProvider"], sess_options=opts
            )
        else:
            self._session = onnxruntime.InferenceSession(path, sess_options=opts)

    def run(self, data: bytes) -> bytes | None:
        json.loads(data)
