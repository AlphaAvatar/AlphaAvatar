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

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .enum.formats import PayloadFormat, PayloadView
from .payload import MediaPayload


class AudioSampleFormat(StrEnum):
    """
    AlphaAvatar-owned audio sample formats.

    Keep this transport-independent. Transport adapters are responsible for
    converting provider-specific audio frames into one of these formats.
    """

    PCM_S16LE = "pcm_s16le"


_SAMPLE_WIDTH_BYTES: dict[AudioSampleFormat, int] = {
    AudioSampleFormat.PCM_S16LE: 2,
}


@dataclass(slots=True, frozen=True)
class AudioFrame:
    """
    Immutable AlphaAvatar-owned audio frame.

    The frame contains interleaved PCM samples.

    For stereo PCM_S16LE, for example, data is laid out as:

        left_0, right_0, left_1, right_1, ...

    This type must remain independent from LiveKit, aiortc, Agora, or any
    other RTC/provider implementation.
    """

    sample_rate: int
    num_channels: int
    samples_per_channel: int
    data: bytes
    sample_format: AudioSampleFormat = AudioSampleFormat.PCM_S16LE

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"Invalid audio sample rate: sample_rate={self.sample_rate}")

        if self.num_channels <= 0:
            raise ValueError(f"Invalid audio channel count: num_channels={self.num_channels}")

        if self.samples_per_channel <= 0:
            raise ValueError(
                f"Invalid samples per channel: samples_per_channel={self.samples_per_channel}"
            )

        if not isinstance(self.data, bytes):
            raise TypeError(
                f"AudioFrame.data must be immutable bytes, got {type(self.data).__name__}"
            )

        expected_size = self.expected_nbytes

        if len(self.data) != expected_size:
            raise ValueError(
                "Audio frame data size does not match its declared shape: "
                f"bytes={len(self.data)}, expected={expected_size}, "
                f"samples_per_channel={self.samples_per_channel}, "
                f"num_channels={self.num_channels}, "
                f"sample_format={self.sample_format.value!r}"
            )

    @property
    def sample_width_bytes(self) -> int:
        return _SAMPLE_WIDTH_BYTES[self.sample_format]

    @property
    def total_samples(self) -> int:
        """
        Total number of interleaved scalar samples across all channels.
        """

        return self.samples_per_channel * self.num_channels

    @property
    def expected_nbytes(self) -> int:
        return self.total_samples * self.sample_width_bytes

    @property
    def duration_sec(self) -> float:
        return self.samples_per_channel / self.sample_rate


class AudioFramePayload(MediaPayload):
    """
    Payload for one logical raw audio frame.

    Available RAW representations:

        AUDIO_FRAME
            AlphaAvatar-owned AudioFrame object.

        AUDIO_PCM16_BYTES
            Interleaved PCM_S16LE bytes.
    """

    def __init__(
        self,
        *,
        frame_id: str | None,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            modality="audio_frame",
            metadata=metadata,
        )

        self.frame_id = frame_id
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.samples_per_channel = samples_per_channel

    @property
    def duration_sec(self) -> float:
        return self.samples_per_channel / self.sample_rate

    @classmethod
    def create(
        cls,
        *,
        frame: AudioFrame,
        frame_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> AudioFramePayload:
        payload = cls(
            frame_id=frame_id,
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            samples_per_channel=frame.samples_per_channel,
            metadata=metadata,
        )

        payload.put(
            PayloadFormat.AUDIO_FRAME,
            frame,
            view=PayloadView.RAW,
        )

        return payload


class AudioSegmentPayload(MediaPayload):
    """
    Payload for one completed canonical audio segment.

    A segment is normally produced by Interaction Router after VAD determines
    that an accepted speech region has ended.

    STT and Persona Speaker should consume this same payload instance or the
    same payload lineage, rather than independently rebuilding the segment.
    """

    def __init__(
        self,
        *,
        segment_id: str,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
        source_observation_ids: Sequence[str],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            modality="audio_segment",
            metadata=metadata,
        )

        self.segment_id = segment_id
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.samples_per_channel = samples_per_channel
        self.source_observation_ids = tuple(source_observation_ids)

    @property
    def duration_sec(self) -> float:
        return self.samples_per_channel / self.sample_rate

    @classmethod
    def create(
        cls,
        *,
        segment_id: str,
        pcm16_bytes: bytes,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
        source_observation_ids: Sequence[str],
        metadata: dict[str, Any] | None = None,
    ) -> AudioSegmentPayload:
        if not segment_id:
            raise ValueError("Audio segment requires a non-empty segment_id")

        if sample_rate <= 0:
            raise ValueError(f"Invalid segment sample rate: sample_rate={sample_rate}")

        if num_channels <= 0:
            raise ValueError(f"Invalid segment channel count: num_channels={num_channels}")

        if samples_per_channel <= 0:
            raise ValueError(
                f"Invalid segment samples per channel: samples_per_channel={samples_per_channel}"
            )

        if not isinstance(pcm16_bytes, bytes):
            raise TypeError(
                "AudioSegmentPayload PCM data must be immutable bytes, "
                f"got {type(pcm16_bytes).__name__}"
            )

        expected_size = samples_per_channel * num_channels * 2

        if len(pcm16_bytes) != expected_size:
            raise ValueError(
                "Audio segment PCM size does not match its declared shape: "
                f"bytes={len(pcm16_bytes)}, expected={expected_size}"
            )

        payload = cls(
            segment_id=segment_id,
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=samples_per_channel,
            source_observation_ids=source_observation_ids,
            metadata=metadata,
        )

        payload.put(
            PayloadFormat.AUDIO_PCM16_BYTES,
            pcm16_bytes,
            view=PayloadView.RAW,
        )

        return payload

    @classmethod
    def from_frames(
        cls,
        *,
        segment_id: str,
        frames: Sequence[AudioFrame],
        source_observation_ids: Sequence[str],
        metadata: dict[str, Any] | None = None,
    ) -> AudioSegmentPayload:
        """
        Build one canonical PCM segment from ordered audio frames.

        Every frame must have the same sample rate, channel count, and sample
        format. The resulting segment performs one byte concatenation when the
        VAD segment is finalized.
        """

        if not frames:
            raise ValueError("Cannot create an audio segment from no frames")

        first = frames[0]

        if first.sample_format != AudioSampleFormat.PCM_S16LE:
            raise ValueError(
                "AudioSegmentPayload currently supports only PCM_S16LE, "
                f"got {first.sample_format.value!r}"
            )

        total_samples_per_channel = 0
        parts: list[bytes] = []

        for index, frame in enumerate(frames):
            if frame.sample_format != first.sample_format:
                raise ValueError(
                    "Audio segment contains mixed sample formats: "
                    f"index={index}, expected={first.sample_format.value!r}, "
                    f"actual={frame.sample_format.value!r}"
                )

            if frame.sample_rate != first.sample_rate:
                raise ValueError(
                    "Audio segment contains mixed sample rates: "
                    f"index={index}, expected={first.sample_rate}, "
                    f"actual={frame.sample_rate}"
                )

            if frame.num_channels != first.num_channels:
                raise ValueError(
                    "Audio segment contains mixed channel counts: "
                    f"index={index}, expected={first.num_channels}, "
                    f"actual={frame.num_channels}"
                )

            total_samples_per_channel += frame.samples_per_channel
            parts.append(frame.data)

        return cls.create(
            segment_id=segment_id,
            pcm16_bytes=b"".join(parts),
            sample_rate=first.sample_rate,
            num_channels=first.num_channels,
            samples_per_channel=total_samples_per_channel,
            source_observation_ids=source_observation_ids,
            metadata=metadata,
        )
