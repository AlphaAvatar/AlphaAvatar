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
import time
from collections.abc import AsyncIterator
from typing import Any

import numpy as np
from livekit import rtc
from livekit.agents import stt, utils, vad
from livekit.agents.job import get_job_context
from livekit.agents.types import APIConnectOptions, NotGivenOr

from alphaavatar.agents.persona import PersonaBase, SpeakerStreamBase

from .models import MODEL_CONFIG
from .runner import SpeakerVectorRunner

STEP_S = 1.0


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

        # Speaker Attribute Inference
        self._inference_frames_attribute: list[rtc.AudioFrame] = []

    async def _inference_speaker_vector(
        self, input_frame: rtc.AudioFrame, timeout: float | None = 1.0
    ) -> None:
        time.perf_counter()

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
        await asyncio.wait_for(
            self._executor.do_inference(
                SpeakerVectorRunner.INFERENCE_METHOD, inference_f32_data.tobytes()
            ),
            timeout=timeout,
        )

    async def _run(self) -> None:
        vad_stream = self._vad.stream()

        recognize_q: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
        speaker_vector_q: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
        _SENTINEL = object()

        async def _queue_iter(q: asyncio.Queue) -> AsyncIterator[Any]:
            """Turn a queue into an async generator with async-for interface."""
            while True:
                item = await q.get()
                if item is _SENTINEL:
                    break
                yield item

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
            finally:
                await recognize_q.put(_SENTINEL)
                await speaker_vector_q.put(_SENTINEL)

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
                    await self._inference_speaker_vector(input_frame)

        tasks = [
            asyncio.create_task(_forward_input(), name="forward_input"),
            asyncio.create_task(_dispatch_events(), name="dispatch"),
            asyncio.create_task(_recognize(), name="recognize"),
            asyncio.create_task(_speaker_vector(), name="speaker_vector"),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            await utils.aio.cancel_and_wait(*tasks)
            await vad_stream.aclose()
