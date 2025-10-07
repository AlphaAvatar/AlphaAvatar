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
from livekit.agents import stt, vad
from livekit.agents.job import get_job_context
from livekit.agents.types import APIConnectOptions, NotGivenOr

from alphaavatar.agents.persona import SpeakerStreamBase

STEP_S = 1.0


class SpeakerProfileStream(SpeakerStreamBase):
    def __init__(
        self,
        stt: stt.STT,
        *,
        vad: vad.VAD,
        wrapped_stt: stt.STT,
        language: NotGivenOr[str],
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(
            stt, vad=vad, wrapped_stt=wrapped_stt, language=language, conn_options=conn_options
        )
        self._executor = get_job_context().inference_executor

    async def _run(self):
        print("((------))", flush=True)
        pass
