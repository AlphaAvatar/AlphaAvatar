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
from contextlib import ExitStack

import onnxruntime

from alphaavatar.agents.persona import IdentifierBase

_resource_files = ExitStack()
atexit.register(_resource_files.close)


def new_inference_session(force_cpu: bool) -> onnxruntime.InferenceSession:
    res = importlib.resources.files("livekit.plugins.silero.resources") / "silero_vad.onnx"
    ctx = importlib.resources.as_file(res)
    path = str(_resource_files.enter_context(ctx))

    opts = onnxruntime.SessionOptions()
    opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
    opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
    opts.inter_op_num_threads = 1
    opts.intra_op_num_threads = 1
    opts.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL

    if force_cpu and "CPUExecutionProvider" in onnxruntime.get_available_providers():
        session = onnxruntime.InferenceSession(
            path, providers=["CPUExecutionProvider"], sess_options=opts
        )
    else:
        session = onnxruntime.InferenceSession(path, sess_options=opts)

    return session


class SpeakerProfile(IdentifierBase):
    def __init__(self):
        super().__init__()
