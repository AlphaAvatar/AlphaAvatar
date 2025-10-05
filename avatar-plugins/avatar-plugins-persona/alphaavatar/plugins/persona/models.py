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

HG_MODEL = "livekit/turn-detector"
ONNX_FILENAME = "model_q8.onnx"


# Speaker Vector Model
SpeakerVectoryModelType = Literal["eres2netv2"]
MODEL_CONFIG: dict[SpeakerVectoryModelType, dict] = {
    "eres2netv2": {
        "revision": "main",
    },
}


# Speaker Attribute Model
