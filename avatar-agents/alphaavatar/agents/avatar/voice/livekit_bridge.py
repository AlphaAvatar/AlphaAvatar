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

from livekit.agents import stt
from livekit.agents.types import APIConnectOptions, NotGivenOr
from livekit.agents.utils import AudioBuffer


class LiveKitSTTBridge(stt.STT):
    """
    Capability marker for the temporary AlphaAvatar STT -> LiveKit turn bridge.

    Actual transcription is produced by AlphaAvatar and yielded through the
    overridden AvatarEngine.stt_node().
    """

    def __init__(self) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
                offline_recognize=False,
            )
        )

    @property
    def provider(self) -> str:
        return "alphaavatar"

    @property
    def model(self) -> str:
        return "external-stt-bridge"

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str],
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        raise RuntimeError(
            "LiveKitSTTBridge does not perform recognition; "
            "AvatarEngine.stt_node supplies external transcription events."
        )
