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
from alphaavatar.agents import AvatarModule, AvatarPlugin

from .log import logger
from .processors import AudioActivityProcessor, SpeechTranscriptionProcessor
from .runtime import InteractionRouterRuntime
from .version import __version__

__all__ = ["__version__"]


class DefaultRouterPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)

    def download_files(self): ...

    def get_plugin(
        self,
        *,
        runtime,
        vad=None,
        stt=None,
        on_transcription=None,
        pre_roll_sec: float = 0.3,
        max_buffer_sec: float = 2.0,
        **kwargs,
    ):
        processors = []

        if stt is not None:
            processors.append(
                AudioActivityProcessor(
                    runtime=runtime,
                    vad=vad,
                    pre_roll_sec=pre_roll_sec,
                    max_buffer_sec=max_buffer_sec,
                )
            )

        if stt is not None:
            if on_transcription is None:
                raise ValueError(
                    "Router requires on_transcription when an STT plugin is configured"
                )

            processors.append(
                SpeechTranscriptionProcessor(
                    runtime=runtime,
                    stt=stt,
                    on_event=on_transcription,
                )
            )

        return InteractionRouterRuntime(
            runtime=runtime,
            processors=processors,
        )


AvatarPlugin.register_avatar_plugin(
    AvatarModule.INTERACTION_ROUTER,
    "default",
    DefaultRouterPlugin(),
)
