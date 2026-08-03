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
"""Transport-independent text-to-speech interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable

from livekit.agents import tts as livekit_tts

from alphaavatar.core.media import AudioFrame


class TTSBase(ABC):
    """
    Transport-independent text-to-speech capability.

    Implementations convert text into AlphaAvatar audio frames. They must not
    publish frames to LiveKit, OutputRuntime, or another transport directly.
    """

    @abstractmethod
    def synthesize(
        self,
        text: str,
    ) -> AsyncIterable[AudioFrame]:
        """Generate normalized AlphaAvatar audio frames."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release provider resources when owned by this instance."""
        return None


class LiveKitTTSAdapter(TTSBase):
    """
    Temporary compatibility adapter for LiveKit Agents TTS providers.

    This adapter can be removed after all TTS implementations directly expose
    the AlphaAvatar TTSBase contract.
    """

    def __init__(
        self,
        provider: livekit_tts.TTS,
        *,
        owns_provider: bool = False,
    ) -> None:
        self._provider = provider
        self._owns_provider = owns_provider

    @property
    def provider(self) -> livekit_tts.TTS:
        return self._provider

    def synthesize(
        self,
        text: str,
    ) -> AsyncIterable[AudioFrame]:
        text = text.strip()

        async def _generate() -> AsyncIterable[AudioFrame]:
            if not text:
                return

            async with self._provider.synthesize(text) as stream:
                async for event in stream:
                    frame = event.frame

                    yield AudioFrame(
                        sample_rate=frame.sample_rate,
                        num_channels=frame.num_channels,
                        samples_per_channel=(frame.samples_per_channel),
                        data=bytes(frame.data),
                    )

        return _generate()

    async def aclose(self) -> None:
        if not self._owns_provider:
            return

        aclose = getattr(self._provider, "aclose", None)
        if callable(aclose):
            await aclose()
