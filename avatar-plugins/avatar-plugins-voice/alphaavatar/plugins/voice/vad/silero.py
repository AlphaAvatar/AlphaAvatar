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
import time
from dataclasses import dataclass

import numpy as np

from alphaavatar.agents.avatar.voice import (
    VADBase,
    VADStreamBase,
    VoiceActivityEvent,
    VoiceActivityEventType,
)
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.core.media import AudioFrame, AudioSampleFormat

from ..log import logger
from .models import SILERO_MODEL_CONFIG
from .runner.silero_runner import SileroVADRunner

_FLUSH = object()
_END_INPUT = object()
_END_EVENTS = object()


@dataclass(slots=True, frozen=True)
class SileroVADOptions:
    min_speech_duration: float = 0.05
    min_silence_duration: float = 0.55
    activation_threshold: float = 0.5
    deactivation_threshold: float = 0.35
    smoothing_alpha: float = 0.35
    queue_size: int = 256
    inference_timeout_sec: float = 0.5
    slow_inference_threshold_sec: float = 0.2


class SileroVAD(VADBase):
    def __init__(
        self,
        *,
        min_speech_duration: float = 0.05,
        min_silence_duration: float = 0.55,
        activation_threshold: float = 0.5,
        deactivation_threshold: float | None = None,
        smoothing_alpha: float = 0.35,
        queue_size: int = 256,
        inference_timeout_sec: float = 0.5,
        inference_executor: InferenceExecutor = None,
    ) -> None:
        if min_speech_duration < 0:
            raise ValueError("min_speech_duration cannot be negative")
        if min_silence_duration < 0:
            raise ValueError("min_silence_duration cannot be negative")
        if not 0 < activation_threshold <= 1:
            raise ValueError("activation_threshold must be in (0, 1]")
        if deactivation_threshold is None:
            deactivation_threshold = max(activation_threshold - 0.15, 0.01)
        if not 0 < deactivation_threshold <= activation_threshold:
            raise ValueError(
                "deactivation_threshold must be positive and no greater than activation_threshold"
            )
        if not 0 <= smoothing_alpha < 1:
            raise ValueError("smoothing_alpha must be in [0, 1)")
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")

        self._options = SileroVADOptions(
            min_speech_duration=min_speech_duration,
            min_silence_duration=min_silence_duration,
            activation_threshold=activation_threshold,
            deactivation_threshold=deactivation_threshold,
            smoothing_alpha=smoothing_alpha,
            queue_size=queue_size,
            inference_timeout_sec=inference_timeout_sec,
        )
        self._inference_executor = inference_executor

    @property
    def model(self) -> str:
        return SILERO_MODEL_CONFIG.model

    @property
    def provider(self) -> str:
        return "onnxruntime-runner"

    @property
    def sample_rate(self) -> int:
        return SILERO_MODEL_CONFIG.sample_rate

    @property
    def update_interval(self) -> float:
        return SILERO_MODEL_CONFIG.update_interval

    def stream(self) -> VADStreamBase:
        return SileroVADStream(
            options=self._options,
            inference_executor=self._inference_executor,
        )


class SileroVADStream(VADStreamBase):
    def __init__(
        self,
        *,
        options: SileroVADOptions,
        inference_executor: InferenceExecutor,
    ) -> None:
        self._options = options
        self._executor = inference_executor

        self._input_q: asyncio.Queue[AudioFrame | object] = asyncio.Queue(
            maxsize=options.queue_size
        )
        self._event_q: asyncio.Queue[VoiceActivityEvent | object] = asyncio.Queue()

        self._pcm_buffer = bytearray()
        self._context = np.zeros(
            SILERO_MODEL_CONFIG.context_size_samples,
            dtype=np.float32,
        )
        self._state = np.zeros(
            SILERO_MODEL_CONFIG.state_shape,
            dtype=np.float32,
        )

        self._samples_index = 0
        self._speaking = False
        self._speech_duration = 0.0
        self._silence_duration = 0.0
        self._raw_speech_duration = 0.0
        self._raw_silence_duration = 0.0
        self._smoothed_probability: float | None = None

        self._accepting_input = True
        self._closed = False
        self._error: BaseException | None = None

        self._worker_task = asyncio.create_task(
            self._run(),
            name="silero_vad_stream",
        )

    def _put_input(self, item: AudioFrame | object) -> bool:
        if self._closed:
            return False

        try:
            self._input_q.put_nowait(item)
            return True
        except asyncio.QueueFull:
            return False

    def push_frame(self, frame: AudioFrame) -> bool:
        if not self._accepting_input or self._closed:
            return False

        if frame.sample_format != AudioSampleFormat.PCM_S16LE:
            raise ValueError(
                f"Silero VAD requires PCM_S16LE audio, got {frame.sample_format.value!r}"
            )
        if frame.sample_rate != SILERO_MODEL_CONFIG.sample_rate:
            raise ValueError(
                f"Silero VAD requires {SILERO_MODEL_CONFIG.sample_rate} Hz audio, "
                f"got {frame.sample_rate}"
            )
        if frame.num_channels != 1:
            raise ValueError(f"Silero VAD requires mono audio, got {frame.num_channels} channels")

        return self._put_input(frame)

    def flush(self) -> bool:
        return self._put_input(_FLUSH)

    def end_input(self) -> bool:
        if not self._accepting_input:
            return False

        if not self._put_input(_END_INPUT):
            return False

        self._accepting_input = False
        return True

    def __aiter__(self):
        return self._iterate_events()

    async def _iterate_events(self):
        while True:
            item = await self._event_q.get()

            if item is _END_EVENTS:
                if self._error is not None:
                    raise RuntimeError("Silero VAD stream failed") from self._error
                return

            yield item

    def _reset_detector_state(self) -> None:
        self._pcm_buffer.clear()
        self._context.fill(0)
        self._state.fill(0)

        self._speaking = False
        self._speech_duration = 0.0
        self._silence_duration = 0.0
        self._raw_speech_duration = 0.0
        self._raw_silence_duration = 0.0
        self._smoothed_probability = None

    def _smooth_probability(self, probability: float) -> float:
        alpha = self._options.smoothing_alpha

        if self._smoothed_probability is None:
            self._smoothed_probability = probability
        else:
            self._smoothed_probability = (
                alpha * self._smoothed_probability + (1.0 - alpha) * probability
            )

        return self._smoothed_probability

    async def _infer(self, audio: np.ndarray) -> tuple[float, float]:
        request = b"".join(
            (
                audio.astype(np.float32, copy=False).tobytes(),
                self._context.tobytes(),
                self._state.tobytes(),
            )
        )

        started = time.perf_counter()
        result = await asyncio.wait_for(
            self._executor.do_inference(
                SileroVADRunner.INFERENCE_METHOD,
                request,
            ),
            timeout=self._options.inference_timeout_sec,
        )
        inference_duration = time.perf_counter() - started

        if result is None:
            raise RuntimeError("Silero VAD runner returned no inference result")

        values = np.frombuffer(result, dtype=np.float32)
        expected_size = 1 + SILERO_MODEL_CONFIG.state_size

        if values.size != expected_size:
            raise RuntimeError(
                f"Invalid Silero response size: values={values.size}, expected={expected_size}"
            )

        probability = float(np.clip(values[0], 0.0, 1.0))
        self._state = values[1:].reshape(SILERO_MODEL_CONFIG.state_shape).copy()
        self._context = audio[-SILERO_MODEL_CONFIG.context_size_samples :].copy()

        return probability, inference_duration

    async def _emit(
        self,
        event_type: VoiceActivityEventType,
        *,
        probability: float | None,
        inference_duration: float,
        speech_duration: float | None = None,
        silence_duration: float | None = None,
        reason: str | None = None,
    ) -> None:
        await self._event_q.put(
            VoiceActivityEvent(
                type=event_type,
                samples_index=self._samples_index,
                timestamp=self._samples_index / SILERO_MODEL_CONFIG.sample_rate,
                input_sample_rate=SILERO_MODEL_CONFIG.sample_rate,
                speaking=self._speaking,
                probability=probability,
                window_samples=SILERO_MODEL_CONFIG.window_size_samples,
                speech_duration=(
                    self._speech_duration if speech_duration is None else speech_duration
                ),
                silence_duration=(
                    self._silence_duration if silence_duration is None else silence_duration
                ),
                inference_duration=inference_duration,
                raw_accumulated_speech=self._raw_speech_duration,
                raw_accumulated_silence=self._raw_silence_duration,
                reason=reason,
            )
        )

    async def _process_window(self, pcm_bytes: bytes) -> None:
        config = SILERO_MODEL_CONFIG
        window_duration = config.update_interval

        audio = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32)
        audio /= float(np.iinfo(np.int16).max)

        probability, inference_duration = await self._infer(audio)
        probability = self._smooth_probability(probability)

        self._samples_index += config.window_size_samples

        if self._speaking:
            self._speech_duration += window_duration
        else:
            self._silence_duration += window_duration

        start_speech = False
        end_speech = False
        final_speech_duration = 0.0

        is_speech = probability >= self._options.activation_threshold or (
            self._speaking and probability > self._options.deactivation_threshold
        )

        if is_speech:
            self._raw_speech_duration += window_duration
            self._raw_silence_duration = 0.0

            if (
                not self._speaking
                and self._raw_speech_duration >= self._options.min_speech_duration
            ):
                self._speaking = True
                self._silence_duration = 0.0
                self._speech_duration = self._raw_speech_duration
                start_speech = True

        else:
            self._raw_silence_duration += window_duration
            self._raw_speech_duration = 0.0

            if self._speaking and self._raw_silence_duration >= self._options.min_silence_duration:
                final_speech_duration = max(
                    0.0,
                    self._speech_duration - self._raw_silence_duration,
                )
                self._speaking = False
                self._silence_duration = self._raw_silence_duration
                end_speech = True

        await self._emit(
            VoiceActivityEventType.INFERENCE_DONE,
            probability=probability,
            inference_duration=inference_duration,
        )

        if start_speech:
            await self._emit(
                VoiceActivityEventType.START_OF_SPEECH,
                probability=probability,
                inference_duration=inference_duration,
                reason="activation_threshold",
            )

        if end_speech:
            await self._emit(
                VoiceActivityEventType.END_OF_SPEECH,
                probability=probability,
                inference_duration=inference_duration,
                speech_duration=final_speech_duration,
                reason="silence_threshold",
            )
            self._speech_duration = 0.0

        if inference_duration > self._options.slow_inference_threshold_sec:
            logger.warning(
                "Silero VAD inference is slower than expected duration=%.3fs update_interval=%.3fs",
                inference_duration,
                config.update_interval,
            )

    async def _finish_input(self) -> None:
        if not self._speaking:
            return

        final_duration = max(
            0.0,
            self._speech_duration - self._raw_silence_duration,
        )
        self._speaking = False

        await self._emit(
            VoiceActivityEventType.END_OF_SPEECH,
            probability=self._smoothed_probability,
            inference_duration=0.0,
            speech_duration=final_duration,
            reason="input_ended",
        )

    async def _run(self) -> None:
        window_bytes = SILERO_MODEL_CONFIG.window_size_samples * 2

        try:
            while True:
                item = await self._input_q.get()

                if item is _FLUSH:
                    self._reset_detector_state()
                    continue

                if item is _END_INPUT:
                    await self._finish_input()
                    break

                if not isinstance(item, AudioFrame):
                    continue

                self._pcm_buffer.extend(item.data)

                while len(self._pcm_buffer) >= window_bytes:
                    window = bytes(self._pcm_buffer[:window_bytes])
                    del self._pcm_buffer[:window_bytes]
                    await self._process_window(window)

        except asyncio.CancelledError:
            raise

        except Exception as error:
            self._error = error
            logger.exception("Silero VAD stream failed")

        finally:
            self._closed = True
            self._accepting_input = False
            self._event_q.put_nowait(_END_EVENTS)

    async def aclose(self) -> None:
        if self._closed and self._worker_task.done():
            return

        self._accepting_input = False

        if not self._worker_task.done():
            self._worker_task.cancel()

        await asyncio.gather(self._worker_task, return_exceptions=True)
        self._closed = True
