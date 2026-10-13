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

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable

from livekit.agents import tts as livekit_tts

from alphaavatar.core.media import AudioFrame


class TTSBase(ABC):
    """Transport-independent TTS with an immutable output PCM format per instance."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Positive sample rate of every emitted AudioFrame."""
        raise NotImplementedError

    @property
    @abstractmethod
    def num_channels(self) -> int:
        """Positive channel count of every emitted AudioFrame."""
        raise NotImplementedError

    @abstractmethod
    def synthesize(self, text: str) -> AsyncIterable[AudioFrame]:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class LiveKitTTSAdapter(TTSBase):
    """Adapt an SDK voice vendor, not an SDK Agent or generation session."""

    def __init__(self, provider: livekit_tts.TTS, *, owns_provider: bool = False) -> None:
        self._provider, self._owns_provider = provider, owns_provider
        self._sample_rate, self._num_channels = provider.sample_rate, provider.num_channels
        if any(
            type(value) is not int or value <= 0
            for value in (self._sample_rate, self._num_channels)
        ):
            raise ValueError("TTS providers must declare a positive integer PCM format")

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def num_channels(self) -> int:
        return self._num_channels

    @property
    def provider(self) -> livekit_tts.TTS:
        return self._provider

    def synthesize(self, text: str) -> AsyncIterable[AudioFrame]:
        text = text.strip()

        async def generate() -> AsyncIterable[AudioFrame]:
            if not text:
                return

            async with self._provider.synthesize(text) as stream:
                async for event in stream:
                    frame = event.frame
                    if (frame.sample_rate, frame.num_channels) != (
                        self._sample_rate,
                        self._num_channels,
                    ):
                        raise ValueError("TTS provider changed its declared PCM format")
                    yield AudioFrame(
                        sample_rate=frame.sample_rate,
                        num_channels=frame.num_channels,
                        samples_per_channel=frame.samples_per_channel,
                        data=bytes(frame.data),
                    )

        return generate()

    async def aclose(self) -> None:
        if self._owns_provider:
            aclose = getattr(self._provider, "aclose", None)
            if callable(aclose):
                await aclose()
