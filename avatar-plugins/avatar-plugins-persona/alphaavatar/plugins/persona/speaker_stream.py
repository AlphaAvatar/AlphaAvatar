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
import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import numpy as np
from livekit import rtc
from livekit.agents import stt, utils, vad
from livekit.agents.job import get_job_context
from livekit.agents.types import APIConnectOptions, NotGivenOr

from alphaavatar.agents.constants import SLOW_INFERENCE_THRESHOLD, SPEAKER_THRESHOLD
from alphaavatar.agents.persona import PersonaBase, SpeakerStreamBase
from alphaavatar.agents.persona.enum.runner_op import VectorRunnerOP
from alphaavatar.agents.utils import DualKeyDict, NumpyOP

from .log import logger
from .models import MODEL_CONFIG
from .runner import QdrantRunner, SpeakerAttributeRunner, SpeakerVectorRunner


@dataclass
class TimeTag:
    timestamp: str
    uid: str | None


class SpeakerStreamWrapper(SpeakerStreamBase):
    def __init__(
        self,
        stt: stt.STT,
        *,
        vad: vad.VAD,
        wrapped_stt: stt.STT,
        language: NotGivenOr[str],
        conn_options: APIConnectOptions,
        activity_persona: PersonaBase,
    ) -> None:
        super().__init__(
            stt,
            vad=vad,
            wrapped_stt=wrapped_stt,
            language=language,
            conn_options=conn_options,
            activity_persona=activity_persona,
        )

        self._executor = get_job_context().inference_executor

        # Speaker Vector Inference
        self._speaker_vector_config = MODEL_CONFIG[SpeakerVectorRunner.MODEL_TYPE]
        self._speaker_vector_frames: list[rtc.AudioFrame] = []
        self._speaker_vector_resampler: rtc.AudioResampler | None = None
        self._speaker_window_duration = (
            self._speaker_vector_config.window_size_samples
            / self._speaker_vector_config.sample_rate
        )

        # Speaker Attribute Inference
        self._speaker_attribute_config = MODEL_CONFIG[SpeakerAttributeRunner.MODEL_TYPE]
        self._speaker_attribute_frames: list[rtc.AudioFrame] = []
        self._speaker_attribute_resampler: rtc.AudioResampler | None = None
        self._speaker_window_duration = (
            self._speaker_attribute_config.window_size_samples
            / self._speaker_attribute_config.sample_rate
        )

        # init frame tagger
        self.frames_tagger: DualKeyDict = DualKeyDict(id_field="uid")

    def slide_frames(
        self, frames: list[rtc.AudioFrame], step_size_samples: int, window_size_samples: int
    ):
        """process remaining frames"""
        step = int(step_size_samples)
        if step <= 0:
            step = int(window_size_samples)

        to_discard = step
        while to_discard > 0 and frames:
            f0 = frames[0]
            n_per_ch = int(f0.samples_per_channel)
            ch = int(f0.num_channels)

            if to_discard >= n_per_ch:
                to_discard -= n_per_ch
                frames.pop(0)
            else:
                start_h = to_discard * ch
                total_h = n_per_ch * ch
                suffix_bytes = f0.data[start_h:total_h].cast("B").tobytes()
                rest_samples = n_per_ch - to_discard
                new_frame = rtc.AudioFrame(
                    data=suffix_bytes,
                    sample_rate=f0.sample_rate,
                    num_channels=f0.num_channels,
                    samples_per_channel=rest_samples,
                )
                frames[0] = new_frame
                to_discard = 0

    async def _inference_speaker_vector(
        self, input_frame: rtc.AudioFrame, timestamp: str, timeout: float | None = 1.0
    ) -> None:
        start_time = time.perf_counter()

        if self._speaker_vector_config.sample_rate != input_frame.sample_rate:
            if not self._speaker_vector_resampler:
                self._speaker_vector_resampler = rtc.AudioResampler(
                    input_frame.sample_rate,
                    self._speaker_vector_config.sample_rate,
                    quality=rtc.AudioResamplerQuality.QUICK,
                )

        if self._speaker_vector_resampler is not None:
            self._speaker_vector_frames.extend(self._speaker_vector_resampler.push(input_frame))
        else:
            self._speaker_vector_frames.append(input_frame)

        available_inference_samples = sum(
            [frame.samples_per_channel for frame in self._speaker_vector_frames]
        )
        if available_inference_samples < self._speaker_vector_config.window_size_samples:
            self.frames_tagger[timestamp] = TimeTag(timestamp, None)  # add a invalid tag
            return

        # convert data to f32
        inference_f32_data = np.empty(
            self._speaker_vector_config.window_size_samples, dtype=np.float32
        )
        inference_frame = utils.combine_frames(self._speaker_vector_frames)
        np.divide(
            inference_frame.data[: self._speaker_vector_config.window_size_samples],
            np.iinfo(np.int16).max,
            out=inference_f32_data,
            dtype=np.float32,
        )

        # infer
        speak_vector_bytes = await asyncio.wait_for(
            self._executor.do_inference(
                SpeakerVectorRunner.INFERENCE_METHOD, inference_f32_data.tobytes()
            ),
            timeout=timeout,
        )
        speaker_vector = np.frombuffer(speak_vector_bytes, dtype=np.float32)  # type: ignore

        inference_duration = time.perf_counter() - start_time
        extra_inference_time = max(
            0.0,
            inference_duration - self._speaker_window_duration,
        )
        if inference_duration > SLOW_INFERENCE_THRESHOLD:
            logger.warning(
                "[SpeakerVector] inference is slower than realtime",
                extra={"delay": extra_inference_time},
            )

        # Match & Retrieve & Update Speaker
        uid = await self._activity_persona.match_speaker_vector(speaker_vector=speaker_vector)
        if uid is not None:
            await self._activity_persona.update_speaker_vector(
                uid=uid, speaker_vector=speaker_vector
            )
        else:
            json_data = {
                "op": VectorRunnerOP.search_speaker_vector,
                "param": {
                    "speaker_vector": NumpyOP.l2_normalize(speaker_vector).tolist(),
                    "threshold": SPEAKER_THRESHOLD,
                },
            }
            json_data = json.dumps(json_data).encode()
            results = await asyncio.wait_for(
                self._executor.do_inference(QdrantRunner.INFERENCE_METHOD, json_data),
                timeout=timeout,
            )
            if results:
                data: dict[str, Any] = json.loads(results.decode())
                uid = data.get("user_id", "")
                await self._activity_persona.load_profile(uid=uid)
                await self._activity_persona.update_speaker_vector(
                    uid=uid, speaker_vector=speaker_vector
                )
            else:
                await self._activity_persona.insert_speaker_vector(speaker_vector=speaker_vector)

        # add frame tag
        self.frames_tagger[timestamp] = TimeTag(timestamp=timestamp, uid=uid)

        # process remaining frames
        self.slide_frames(
            self._speaker_vector_frames,
            self._speaker_vector_config.step_size_samples,
            self._speaker_vector_config.window_size_samples,
        )

    async def _inference_speaker_attribute(
        self, input_frame: rtc.AudioFrame, timestamp: str, timeout: float | None = 1.0
    ) -> None:
        start_time = time.perf_counter()

        if self._speaker_attribute_config.sample_rate != input_frame.sample_rate:
            if not self._speaker_attribute_resampler:
                self._speaker_attribute_resampler = rtc.AudioResampler(
                    input_frame.sample_rate,
                    self._speaker_attribute_config.sample_rate,
                    quality=rtc.AudioResamplerQuality.QUICK,
                )

        if self._speaker_attribute_resampler is not None:
            self._speaker_attribute_frames.extend(
                self._speaker_attribute_resampler.push(input_frame)
            )
        else:
            self._speaker_attribute_frames.append(input_frame)

        available_inference_samples = sum(
            [frame.samples_per_channel for frame in self._speaker_attribute_frames]
        )
        if available_inference_samples < self._speaker_attribute_config.window_size_samples:
            return

        # wait
        wait_budget = 2.0 if timeout is None else timeout
        poll_interval = 0.01
        elapsed = 0.0
        while timestamp not in self.frames_tagger:
            if elapsed >= wait_budget:
                self.slide_frames(
                    self._speaker_attribute_frames,
                    self._speaker_attribute_config.step_size_samples,
                    self._speaker_attribute_config.window_size_samples,
                )
                return
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # infer
        time_tag: TimeTag = self.frames_tagger[timestamp]
        if time_tag.uid:
            inference_f32_data = np.empty(
                self._speaker_attribute_config.window_size_samples, dtype=np.float32
            )
            inference_frame = utils.combine_frames(self._speaker_attribute_frames)
            np.divide(
                inference_frame.data[: self._speaker_attribute_config.window_size_samples],
                np.iinfo(np.int16).max,
                out=inference_f32_data,
                dtype=np.float32,
            )

            result = await asyncio.wait_for(
                self._executor.do_inference(
                    SpeakerAttributeRunner.INFERENCE_METHOD, inference_f32_data.tobytes()
                ),
                timeout=timeout,
            )

            inference_duration = time.perf_counter() - start_time
            extra_inference_time = max(
                0.0,
                inference_duration - self._speaker_window_duration,
            )
            if inference_duration > SLOW_INFERENCE_THRESHOLD:
                logger.warning(
                    "[SpeakerAttribute] inference is slower than realtime",
                    extra={"delay": extra_inference_time},
                )

            speaker_attribute: dict[str, np.ndarray] = SpeakerAttributeRunner.decode(result)  # type: ignore
            await self._activity_persona.update_speaker_attribute(
                uid=time_tag.uid, speaker_attribute=speaker_attribute
            )

        # process remaining frames
        self.slide_frames(
            self._speaker_attribute_frames,
            self._speaker_attribute_config.step_size_samples,
            self._speaker_attribute_config.window_size_samples,
        )

    async def _run(self) -> None:
        vad_stream = self._vad.stream()

        recognize_q: asyncio.Queue[vad.VADEvent | Any] = asyncio.Queue(maxsize=256)
        speaker_vector_q: asyncio.Queue[vad.VADEvent | Any] = asyncio.Queue(maxsize=256)
        speaker_attribute_q: asyncio.Queue[vad.VADEvent | Any] = asyncio.Queue(maxsize=256)
        _SENTINEL = object()

        async def _queue_iter(q: asyncio.Queue) -> AsyncIterator[vad.VADEvent]:
            """Turn a queue into an async generator with async-for interface."""
            while True:
                item = await q.get()
                if item is _SENTINEL:
                    break
                yield item

        # Dispath
        async def _forward_input() -> None:
            """forward input to vad"""
            async for input in self._input_ch:
                if isinstance(input, self._FlushSentinel):
                    vad_stream.flush()
                    continue
                vad_stream.push_frame(input)
            vad_stream.end_input()

        async def _dispatch_events() -> None:
            try:
                async for event in vad_stream:
                    await recognize_q.put(event)
                    await speaker_vector_q.put(event)
                    await speaker_attribute_q.put(event)
            finally:
                await recognize_q.put(_SENTINEL)
                await speaker_vector_q.put(_SENTINEL)
                await speaker_attribute_q.put(_SENTINEL)

        # Parallel threads
        async def _recognize() -> None:
            """recognize speech from vad"""
            async for event in _queue_iter(recognize_q):
                if event.type == vad.VADEventType.START_OF_SPEECH:
                    self._event_ch.send_nowait(stt.SpeechEvent(stt.SpeechEventType.START_OF_SPEECH))
                elif event.type == vad.VADEventType.END_OF_SPEECH:
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(
                            type=stt.SpeechEventType.END_OF_SPEECH,
                        )
                    )

                    merged_frames = utils.merge_frames(event.frames)
                    t_event = await self._wrapped_stt.recognize(
                        buffer=merged_frames,
                        language=self._language,
                        conn_options=self._wrapped_stt_conn_options,
                    )

                    if len(t_event.alternatives) == 0:
                        continue
                    elif not t_event.alternatives[0].text:
                        continue

                    self._event_ch.send_nowait(
                        stt.SpeechEvent(
                            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                            alternatives=[t_event.alternatives[0]],
                        )
                    )

        async def _speaker_vector() -> None:
            async for event in _queue_iter(speaker_vector_q):
                if event.type == vad.VADEventType.END_OF_SPEECH:
                    input_frame = utils.merge_frames(event.frames)
                    await self._inference_speaker_vector(
                        input_frame, timestamp=str(event.timestamp)
                    )

        async def _speaker_attribute() -> None:
            async for event in _queue_iter(speaker_attribute_q):
                if event.type == vad.VADEventType.END_OF_SPEECH:
                    input_frame = utils.merge_frames(event.frames)
                    await self._inference_speaker_attribute(
                        input_frame, timestamp=str(event.timestamp)
                    )

        # Run
        tasks = [
            asyncio.create_task(_forward_input(), name="forward_input"),
            asyncio.create_task(_dispatch_events(), name="dispatch"),
            asyncio.create_task(_recognize(), name="recognize"),
            asyncio.create_task(_speaker_vector(), name="speaker_vector"),
            asyncio.create_task(_speaker_attribute(), name="speaker_attribute"),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            await utils.aio.cancel_and_wait(*tasks)
            await vad_stream.aclose()
