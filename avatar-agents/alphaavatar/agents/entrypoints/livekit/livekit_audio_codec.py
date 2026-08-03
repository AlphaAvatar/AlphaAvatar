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

import sys
from array import array

from alphaavatar.core.media import AudioFrame, AudioSampleFormat
from livekit import rtc


def _to_pcm_s16le_bytes(frame: rtc.AudioFrame) -> bytes:
    required_size = frame.samples_per_channel * frame.num_channels * 2
    data = frame.data.cast("B")[:required_size].tobytes()

    if sys.byteorder == "little":
        return data

    samples = array("h")
    samples.frombytes(data)
    samples.byteswap()
    return samples.tobytes()


def _to_native_pcm16_bytes(frame: AudioFrame) -> bytes:
    if frame.sample_format != AudioSampleFormat.PCM_S16LE:
        raise ValueError(
            "LiveKit audio adapter currently supports only PCM_S16LE, "
            f"got {frame.sample_format.value!r}"
        )

    if sys.byteorder == "little":
        return frame.data

    samples = array("h")
    samples.frombytes(frame.data)
    samples.byteswap()
    return samples.tobytes()


def from_livekit_audio_frame(frame: rtc.AudioFrame) -> AudioFrame:
    """
    Convert one LiveKit audio frame into an AlphaAvatar-owned audio frame.

    LiveKit may expose a buffer larger than the declared frame shape, so only
    the exact declared sample region is copied.
    """

    return AudioFrame(
        sample_rate=frame.sample_rate,
        num_channels=frame.num_channels,
        samples_per_channel=frame.samples_per_channel,
        data=_to_pcm_s16le_bytes(frame),
    )


def to_livekit_audio_frame(frame: AudioFrame) -> rtc.AudioFrame:
    """
    Convert an AlphaAvatar-owned audio frame back into a LiveKit frame.

    This compatibility conversion will later be used by the LiveKit VAD and
    STT adapters while the core and plugins remain RTC-independent.
    """

    return rtc.AudioFrame(
        data=_to_native_pcm16_bytes(frame),
        sample_rate=frame.sample_rate,
        num_channels=frame.num_channels,
        samples_per_channel=frame.samples_per_channel,
    )
