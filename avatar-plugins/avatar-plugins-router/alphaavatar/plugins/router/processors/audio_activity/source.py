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

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass

from alphaavatar.agents.avatar.voice import (
    VADBase,
    VADStreamBase,
    VoiceActivityEvent,
    VoiceActivityEventType,
)
from alphaavatar.core.env import (
    EnvObservation,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import AudioFrame, AudioSegmentPayload
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.time import RuntimeTimeRange

from ...log import logger


@dataclass(slots=True)
class AudioFrameRef:
    observation: EnvObservation
    frame: AudioFrame
    start_sample: int
    end_sample: int
    routed_segment: PerceptionSegmentRef | None = None


class AudioActivitySource:
    def __init__(
        self,
        *,
        perception_runtime: PerceptionRuntime,
        input_source: PerceptionSourceRef,
        vad: VADBase,
        sample_rate: int,
        num_channels: int,
        pre_roll_sec: float,
        max_buffer_sec: float,
    ) -> None:
        self.perception_runtime = perception_runtime
        self.input_source = input_source
        self.speech_source = PerceptionSourceRef(
            source_id=f"router:speech:{input_source.source_id}",
            source_generation=input_source.source_generation,
        )

        self.sample_rate = sample_rate
        self.num_channels = num_channels

        self._pre_roll_samples = int(pre_roll_sec * sample_rate)
        self._max_buffer_samples = int(max_buffer_sec * sample_rate)
        self._vad_stream: VADStreamBase = vad.stream()

        self._pending: deque[AudioFrameRef] = deque()
        self._segment_frames: list[AudioFrameRef] = []

        self._next_sample = 0
        self._segment: PerceptionSegmentRef | None = None
        self._speech_start_sample = 0
        self._route_start_sample = 0
        self._route_index = 0

        self.failed = False
        self._closed = False

        self._event_task = asyncio.create_task(
            self._event_loop(),
            name=(
                f"router_audio_activity_vad:"
                f"{input_source.source_id}:"
                f"{input_source.source_generation}"
            ),
        )

    @property
    def speaking(self) -> bool:
        return self._segment is not None

    def matches(self, frame: AudioFrame) -> bool:
        return frame.sample_rate == self.sample_rate and frame.num_channels == self.num_channels

    def _append_frame(
        self,
        observation: EnvObservation,
        frame: AudioFrame,
    ) -> AudioFrameRef:
        frame_ref = AudioFrameRef(
            observation=observation,
            frame=frame,
            start_sample=self._next_sample,
            end_sample=self._next_sample + frame.samples_per_channel,
        )

        self._next_sample = frame_ref.end_sample
        self._pending.append(frame_ref)

        earliest = max(0, self._next_sample - self._max_buffer_samples)

        while self._pending and self._pending[0].end_sample <= earliest:
            self._pending.popleft()

        return frame_ref

    def push(
        self,
        observation: EnvObservation,
        frame: AudioFrame,
    ) -> bool:
        if self._closed or observation.source != self.input_source:
            return False

        frame_ref = self._append_frame(observation, frame)

        if not self._vad_stream.push_frame(frame):
            if self._pending and self._pending[-1] is frame_ref:
                self._pending.pop()
            return False

        if self.speaking:
            self._publish_speech_frame(frame_ref)

        return True

    def _publish_speech_frame(
        self,
        frame_ref: AudioFrameRef,
        *,
        speech_start: bool = False,
    ) -> EnvObservation | None:
        segment = self._segment

        if segment is None or frame_ref.routed_segment == segment:
            return None

        self._route_index += 1

        metadata = {
            "route_index": self._route_index,
            "is_pre_roll": frame_ref.start_sample < self._speech_start_sample,
            "source_observation_id": frame_ref.observation.observation_id,
            "source_frame_id": frame_ref.observation.frame_id,
            "router_processor": "audio_activity",
        }
        if speech_start:
            metadata["speech_event"] = "start"

        routed = EnvObservation.speech_frame(
            time_range=frame_ref.observation.time_range,
            source=self.speech_source,
            segment=segment,
            transport_participant_id=frame_ref.observation.transport_participant_id,
            entity=frame_ref.observation.entity,
            payload=frame_ref.observation.payload,
            metadata=metadata,
        )

        self.perception_runtime.publish_observation(routed)

        frame_ref.routed_segment = segment
        self._segment_frames.append(frame_ref)
        return routed

    def _start_segment(self, event: VoiceActivityEvent) -> None:
        if self.speaking:
            return

        accumulated = int(event.raw_accumulated_speech * self.sample_rate)
        self._speech_start_sample = max(0, event.samples_index - accumulated)
        self._route_start_sample = max(0, self._speech_start_sample - self._pre_roll_samples)

        self._segment = PerceptionSegmentRef(
            source=self.speech_source,
            segment_id=uuid.uuid4().hex,
        )
        self._segment_frames.clear()
        self._route_index = 0

        first = True

        for frame_ref in self._pending:
            if frame_ref.end_sample <= self._route_start_sample:
                continue

            routed = self._publish_speech_frame(
                frame_ref,
                speech_start=first,
            )

            if routed is not None:
                first = False

    def _time_at_sample(
        self,
        frames: list[AudioFrameRef],
        sample: int,
    ):
        for frame_ref in frames:
            if frame_ref.start_sample <= sample <= frame_ref.end_sample:
                offset_sec = (sample - frame_ref.start_sample) / self.sample_rate
                return frame_ref.observation.time_range.start.shifted(offset_sec)

        return None

    def _finish_segment(self, event: VoiceActivityEvent) -> None:
        segment = self._segment
        if segment is None:
            return

        trailing_silence = int(event.raw_accumulated_silence * self.sample_rate)
        speech_end = max(
            self._speech_start_sample,
            event.samples_index - trailing_silence,
        )

        frames = [
            frame_ref for frame_ref in self._segment_frames if frame_ref.start_sample < speech_end
        ]

        if frames:
            segment_start = self._time_at_sample(
                frames,
                self._speech_start_sample,
            )
            segment_end = self._time_at_sample(
                frames,
                speech_end,
            )

            if segment_start is None or segment_end is None:
                segment_range = RuntimeTimeRange(
                    start=frames[0].observation.time_range.start,
                    end=frames[-1].observation.time_range.end,
                )
            else:
                segment_range = RuntimeTimeRange(
                    start=segment_start,
                    end=segment_end,
                )

            source_observation_ids = [frame_ref.observation.observation_id for frame_ref in frames]

            metadata = {
                "speech_event": "end",
                "sample_rate": self.sample_rate,
                "num_channels": self.num_channels,
                "route_start_sample": self._route_start_sample,
                "speech_start_sample": self._speech_start_sample,
                "speech_end_sample": speech_end,
                "frame_count": len(frames),
                "speech_duration": event.speech_duration,
                "silence_duration": event.silence_duration,
                "vad_probability": event.probability,
                "vad_reason": event.reason,
            }

            payload = AudioSegmentPayload.from_frames(
                segment_id=segment.segment_id,
                frames=[frame_ref.frame for frame_ref in frames],
                source_observation_ids=source_observation_ids,
                metadata=dict(metadata),
            )

            first_observation = frames[0].observation

            speech_segment = EnvObservation.speech_segment(
                time_range=segment_range,
                source=self.speech_source,
                segment=segment,
                transport_participant_id=first_observation.transport_participant_id,
                entity=first_observation.entity,
                payload=payload,
                metadata=metadata,
            )

            self.perception_runtime.publish_observation(speech_segment)

        self._segment = None
        self._segment_frames.clear()
        self._route_index = 0

    async def _event_loop(self) -> None:
        try:
            async for event in self._vad_stream:
                if event.type == VoiceActivityEventType.START_OF_SPEECH:
                    self._start_segment(event)
                elif event.type == VoiceActivityEventType.END_OF_SPEECH:
                    self._finish_segment(event)

        except asyncio.CancelledError:
            raise
        except Exception:
            self.failed = True
            logger.exception(
                "Audio Activity VAD failed source=%s",
                self.input_source,
            )

    async def close(self, *, graceful: bool) -> None:
        if self._closed:
            return

        self._closed = True

        if graceful and self._vad_stream.end_input():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._event_task),
                    timeout=1.0,
                )
            except TimeoutError:
                pass

        if not self._event_task.done():
            self._event_task.cancel()

        await self._vad_stream.aclose()
        await asyncio.gather(self._event_task, return_exceptions=True)

        self._pending.clear()
        self._segment_frames.clear()
