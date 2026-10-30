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
import logging
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from alphaavatar.agents.avatar.voice import (
    VADBase,
    VADStreamBase,
    VoiceActivityEvent,
    VoiceActivityEventType,
)
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import SpeechCancellationReason
from alphaavatar.core.env.schemas import PerceptionSegmentRef, PerceptionSourceRef
from alphaavatar.core.media import AudioFrame, AudioSegmentPayload
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.time import RuntimeTimeRange

logger = logging.getLogger(__name__)


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
        close_timeout_sec: float = 1.0,
        on_failed: Callable[[AudioActivitySource, SpeechCancellationReason], None] | None = None,
    ) -> None:
        self.perception_runtime = perception_runtime
        self.input_source = input_source
        self.speech_source = perception_runtime.next_source(
            f"router:speech:{input_source.source_id}"
        )

        self.sample_rate = sample_rate
        self.num_channels = num_channels

        self._pre_roll_samples = int(pre_roll_sec * sample_rate)
        self._max_buffer_samples = int(max_buffer_sec * sample_rate)
        self._vad_stream: VADStreamBase = vad.stream()
        self._close_timeout_sec = close_timeout_sec
        self._on_failed = on_failed

        self._pending: deque[AudioFrameRef] = deque()
        self._segment_frames: list[AudioFrameRef] = []

        self._next_sample = 0
        self._segment: PerceptionSegmentRef | None = None
        self._speech_start_sample = 0
        self._route_start_sample = 0
        self._route_index = 0

        self.failed = False
        self._closed = False
        self._aborted = False
        self._close_task: asyncio.Task[None] | None = None
        self._provider_close_task: asyncio.Task[None] | None = None

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

    @property
    def cleanup_tasks(self) -> tuple[asyncio.Task[None], ...]:
        return tuple(
            task
            for task in (self._event_task, self._provider_close_task, self._close_task)
            if task is not None
        )

    def matches(self, frame: AudioFrame) -> bool:
        return frame.sample_rate == self.sample_rate and frame.num_channels == self.num_channels

    def _append_frame(self, observation: EnvObservation, frame: AudioFrame) -> AudioFrameRef:
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

    def push(self, observation: EnvObservation, frame: AudioFrame) -> bool:
        if self._closed or self.failed or observation.source != self.input_source:
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
        self, frame_ref: AudioFrameRef, *, speech_start: bool = False
    ) -> EnvObservation | None:
        segment = self._segment

        if self._aborted or segment is None or frame_ref.routed_segment == segment:
            return None

        self._route_index += 1

        metadata = {
            "route_index": self._route_index,
            "is_pre_roll": frame_ref.start_sample < self._speech_start_sample,
            "source_observation_id": frame_ref.observation.observation_id,
            "source_frame_id": frame_ref.observation.frame_id,
            "router_processor": "audio_activity",
            "input_source": self.input_source.to_dict(),
        }
        if speech_start:
            metadata["speech_event"] = "start"

        routed = EnvObservation.speech_frame(
            time_range=frame_ref.observation.time_range,
            source=self.speech_source,
            segment=segment,
            device_id=frame_ref.observation.device_id,
            entity=frame_ref.observation.entity,
            payload=frame_ref.observation.payload,
            metadata=metadata,
        )

        self.perception_runtime.publish_observation(routed)

        frame_ref.routed_segment = segment
        self._segment_frames.append(frame_ref)
        return routed

    def _start_segment(self, event: VoiceActivityEvent) -> None:
        if self._aborted or self.speaking:
            return

        accumulated = int(event.raw_accumulated_speech * self.sample_rate)
        self._speech_start_sample = max(0, event.samples_index - accumulated)
        self._route_start_sample = max(0, self._speech_start_sample - self._pre_roll_samples)

        self._segment = PerceptionSegmentRef(source=self.speech_source, segment_id=uuid.uuid4().hex)
        self._segment_frames.clear()
        self._route_index = 0

        first = True

        for frame_ref in self._pending:
            if frame_ref.end_sample <= self._route_start_sample:
                continue

            routed = self._publish_speech_frame(frame_ref, speech_start=first)

            if routed is not None:
                first = False

    def _time_at_sample(self, frames: list[AudioFrameRef], sample: int):
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
        speech_end = max(self._speech_start_sample, event.samples_index - trailing_silence)

        frames = [
            frame_ref for frame_ref in self._segment_frames if frame_ref.start_sample < speech_end
        ]

        if not frames:
            self._fail(SpeechCancellationReason.EMPTY_SEGMENT)
            return

        segment_start = self._time_at_sample(frames, self._speech_start_sample)
        segment_end = self._time_at_sample(frames, speech_end)

        if segment_start is None or segment_end is None:
            segment_range = RuntimeTimeRange(
                start=frames[0].observation.time_range.start,
                end=frames[-1].observation.time_range.end,
            )
        else:
            segment_range = RuntimeTimeRange(start=segment_start, end=segment_end)

        source_observation_ids = [frame_ref.observation.observation_id for frame_ref in frames]

        metadata = {
            "speech_event": "end",
            "input_source": self.input_source.to_dict(),
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
            device_id=first_observation.device_id,
            entity=first_observation.entity,
            payload=payload,
            metadata=metadata,
        )

        self.perception_runtime.publish_observation(speech_segment)

        self._segment = None
        self._segment_frames.clear()
        self._route_index = 0

    def _abort(self, reason: SpeechCancellationReason) -> None:
        self._closed = self._aborted = True
        segment, self._segment = self._segment, None
        if segment is not None:
            first = self._segment_frames[0].observation if self._segment_frames else None
            self.perception_runtime.publish_observation(
                EnvObservation.speech_cancelled(
                    reason=reason,
                    source=self.speech_source,
                    segment=segment,
                    time_range=RuntimeTimeRange.point(self.perception_runtime.clock.now()),
                    device_id=first.device_id if first else None,
                    entity=first.entity if first else None,
                    metadata={
                        "input_source": self.input_source.to_dict(),
                        "frame_count": self._route_index,
                        "router_processor": "audio_activity",
                    },
                )
            )
        self._pending.clear()
        self._segment_frames.clear()
        self._route_index = 0

    def _fail(self, reason: SpeechCancellationReason) -> None:
        self.failed = True
        self._abort(reason)
        if self._on_failed is not None:
            self._on_failed(self, reason)
        else:
            self.begin_close(graceful=False, reason=reason)

    async def _event_loop(self) -> None:
        try:
            async for event in self._vad_stream:
                if self._aborted:
                    break
                if event.type == VoiceActivityEventType.START_OF_SPEECH:
                    self._start_segment(event)
                elif event.type == VoiceActivityEventType.END_OF_SPEECH:
                    self._finish_segment(event)

        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail(SpeechCancellationReason.VAD_ERROR)
            logger.exception("Audio Activity VAD failed source=%s", self.input_source)
        else:
            if not self._closed:
                self._fail(SpeechCancellationReason.VAD_ENDED)

    def begin_close(
        self,
        *,
        graceful: bool,
        reason: SpeechCancellationReason = SpeechCancellationReason.SOURCE_CLOSED,
    ) -> asyncio.Task[None]:
        self._closed = True
        if not graceful:
            # Publish the terminal before waiting for any provider resource to close.
            self._abort(reason)
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                self._close(graceful=graceful, reason=reason),
                name=(
                    f"router_audio_activity_close:{self.speech_source.source_id}:"
                    f"{self.speech_source.source_generation}"
                ),
            )
        return self._close_task

    async def _close(self, *, graceful: bool, reason: SpeechCancellationReason) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._close_timeout_sec
        try:
            if graceful and not self._aborted and self._vad_stream.end_input():
                _, pending = await asyncio.wait(
                    (self._event_task,), timeout=max(0.0, deadline - loop.time())
                )
                if pending:
                    reason = SpeechCancellationReason.CLOSE_TIMEOUT
        except asyncio.CancelledError:
            raise
        except Exception:
            reason = SpeechCancellationReason.PROCESSING_ERROR
            logger.exception("Audio Activity drain failed source=%s", self.input_source)
        finally:
            self._abort(reason)
            if not self._event_task.done():
                self._event_task.cancel()
            self._provider_close_task = asyncio.create_task(
                self._vad_stream.aclose(), name="router_audio_activity_provider_close"
            )
            tasks = (self._event_task, self._provider_close_task)
            try:
                done, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline - loop.time()))
                for task in done:
                    if not task.cancelled() and task.exception() is not None:
                        logger.warning("Audio Activity cleanup failed source=%s", self.input_source)
                if pending:
                    self.perception_runtime.input_trace.record(
                        "audio.close_timeout",
                        source_id=self.speech_source.source_id,
                        source_generation=self.speech_source.source_generation,
                        input_source_id=self.input_source.source_id,
                        input_source_generation=self.input_source.source_generation,
                        reason="close_timeout",
                    )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()

    async def close(
        self,
        *,
        graceful: bool,
        reason: SpeechCancellationReason = SpeechCancellationReason.SOURCE_CLOSED,
    ) -> None:
        await asyncio.shield(self.begin_close(graceful=graceful, reason=reason))
