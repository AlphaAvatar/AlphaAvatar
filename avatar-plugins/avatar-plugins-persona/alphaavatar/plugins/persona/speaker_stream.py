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
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from alphaavatar.agents.constants import SPEAKER_MATCH_THRESHOLD
from alphaavatar.agents.persona import PersonaBase, SpeakerStreamBase, VectorRunnerOP
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.utils import NumpyOP
from alphaavatar.core.env import (
    EnvObservation,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import (
    AudioFrame,
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
)
from alphaavatar.core.perception import PerceptionStreamKind

from .log import logger
from .model_files import SPEAKER_MODEL_CONFIG
from .runner import SpeakerAttributeRunner, SpeakerVectorRunner

_STOP = object()


@dataclass(slots=True)
class SpeakerSourceState:
    source: PerceptionSourceRef
    sample_rate: int
    num_channels: int
    pcm: bytearray = field(default_factory=bytearray)
    window_index: int = 0
    seen_observation_ids: set[str] = field(default_factory=set)
    seen_order: deque[str] = field(default_factory=deque)


@dataclass(slots=True, frozen=True)
class SpeakerWindow:
    source: PerceptionSourceRef
    segment: PerceptionSegmentRef | None
    window_index: int
    audio_f32: bytes


class SpeakerStreamWrapper(SpeakerStreamBase):
    CONSUMER_ID = "persona.speaker"

    MAX_SEEN_OBSERVATIONS = 2048
    ATTRIBUTE_INTERVAL_SEC = 5.0

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        activity_persona: PersonaBase,
        inference_queue_size: int = 1,
    ) -> None:
        super().__init__(runtime=runtime, activity_persona=activity_persona)

        self._vector_config = SPEAKER_MODEL_CONFIG[SpeakerVectorRunner.MODEL_TYPE]
        self._attribute_config = SPEAKER_MODEL_CONFIG[SpeakerAttributeRunner.MODEL_TYPE]

        if self._vector_config.sample_rate != self._attribute_config.sample_rate:
            raise ValueError("Speaker vector and attribute models must use the same sample rate")

        self._sample_rate = self._vector_config.sample_rate
        self._window_samples = self._vector_config.window_size_samples
        self._step_samples = self._vector_config.step_size_samples

        self._window_bytes = self._window_samples * 2
        self._step_bytes = self._step_samples * 2

        self._step_sec = self._step_samples / self._sample_rate
        self._attribute_every = max(
            1,
            math.ceil(self.ATTRIBUTE_INTERVAL_SEC / self._step_sec),
        )

        self._sources: dict[PerceptionSourceRef, SpeakerSourceState] = {}
        self._inference_queue: asyncio.Queue[SpeakerWindow | object] = asyncio.Queue(
            maxsize=inference_queue_size
        )

        self._consume_task: asyncio.Task[None] | None = None
        self._inference_task: asyncio.Task[None] | None = None
        self._started = False

    @property
    def vdb_inference_method(self) -> str:
        method = os.getenv("PERSONA_VDB_INFERENCE_METHOD")
        if not method:
            raise RuntimeError(
                "PERSONA_VDB_INFERENCE_METHOD is not configured. "
                "Make sure the Persona VDB runner is registered before "
                "SpeakerStreamWrapper starts."
            )
        return method

    def _extract_frame(self, observation: EnvObservation) -> AudioFrame | None:
        if observation.payload is None:
            return None

        try:
            frame = observation.payload.get(
                PayloadFormat.AUDIO_FRAME,
                view=PayloadView.RAW,
                fallback_to_raw=False,
            )
        except PayloadFormatUnavailable:
            return None

        return frame if isinstance(frame, AudioFrame) else None

    def _remember_observation(
        self,
        state: SpeakerSourceState,
        observation_id: str,
    ) -> bool:
        if observation_id in state.seen_observation_ids:
            return False

        state.seen_observation_ids.add(observation_id)
        state.seen_order.append(observation_id)

        while len(state.seen_order) > self.MAX_SEEN_OBSERVATIONS:
            removed = state.seen_order.popleft()
            state.seen_observation_ids.discard(removed)

        return True

    def _enqueue_window(self, window: SpeakerWindow) -> None:
        try:
            self._inference_queue.put_nowait(window)
            return
        except asyncio.QueueFull:
            pass

        try:
            self._inference_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        try:
            self._inference_queue.put_nowait(window)
        except asyncio.QueueFull:
            logger.warning(
                "Speaker inference queue is full source_id=%s generation=%s window_index=%s",
                window.source.source_id,
                window.source.source_generation,
                window.window_index,
            )

    def _append_frame(self, observation: EnvObservation, frame: AudioFrame) -> None:
        source = observation.source
        if frame.sample_rate != self._sample_rate or frame.num_channels != 1:
            logger.warning(
                "Speaker received unsupported audio "
                "source_id=%s generation=%s sample_rate=%s channels=%s",
                source.source_id,
                source.source_generation,
                frame.sample_rate,
                frame.num_channels,
            )
            return

        state = self._sources.get(source)
        if state is None:
            state = SpeakerSourceState(
                source=source,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
            )
            self._sources[source] = state

        # Adjacent speech segments may reuse the same raw pre-roll observation.
        # Persona Speaker should consume that source observation only once.
        source_observation_id = str(
            observation.metadata.get("source_observation_id") or observation.observation_id
        )
        if not self._remember_observation(state, source_observation_id):
            return

        state.pcm.extend(frame.data)

        while len(state.pcm) >= self._window_bytes:
            pcm16 = bytes(state.pcm[: self._window_bytes])
            audio = np.frombuffer(pcm16, dtype="<i2").astype(np.float32)
            audio /= 32768.0

            state.window_index += 1

            self._enqueue_window(
                SpeakerWindow(
                    source=source,
                    segment=observation.segment,
                    window_index=state.window_index,
                    audio_f32=audio.tobytes(),
                )
            )

            del state.pcm[: self._step_bytes]

    """Inference worker"""

    async def _resolve_speaker(self, window: SpeakerWindow) -> str | None:
        result = await asyncio.wait_for(
            self.inference_executor.do_inference(
                SpeakerVectorRunner.INFERENCE_METHOD,
                window.audio_f32,
            ),
            timeout=self._vector_config.inference_timeout_sec,
        )

        if result is None:
            raise RuntimeError("Speaker vector runner returned no result")

        speaker_vector = np.frombuffer(result, dtype=np.float32)
        uid = await self.activity_persona.match_speaker_vector(speaker_vector=speaker_vector)

        if uid is not None:
            await self.activity_persona.update_speaker_vector(
                uid=uid,
                speaker_vector=speaker_vector,
            )
            return uid

        request = {
            "op": VectorRunnerOP.search_speaker_vector,
            "param": {
                "speaker_vector": NumpyOP.l2_normalize(speaker_vector).tolist(),
                "threshold": SPEAKER_MATCH_THRESHOLD,
            },
        }

        search_result = await asyncio.wait_for(
            self.inference_executor.do_inference(
                self.vdb_inference_method,
                json.dumps(request).encode(),
            ),
            timeout=self._vector_config.inference_timeout_sec,
        )

        if search_result:
            data: dict[str, Any] = json.loads(search_result.decode())
            uid = data.get("user_id") or None

            if uid is not None:
                await self.activity_persona.load_profile(uid=uid)
                await self.activity_persona.update_speaker_vector(
                    uid=uid,
                    speaker_vector=speaker_vector,
                )
                return uid

        return await self.activity_persona.insert_speaker_vector(speaker_vector=speaker_vector)

    async def _infer_attribute(
        self,
        window: SpeakerWindow,
        uid: str,
    ) -> None:
        result = await asyncio.wait_for(
            self.inference_executor.do_inference(
                SpeakerAttributeRunner.INFERENCE_METHOD,
                window.audio_f32,
            ),
            timeout=self._attribute_config.inference_timeout_sec,
        )

        if result is None:
            raise RuntimeError("Speaker attribute runner returned no result")

        speaker_attribute: dict[str, np.ndarray] = SpeakerAttributeRunner.decode(result)  # type: ignore
        await self.activity_persona.update_speaker_attribute(
            uid=uid,
            speaker_attribute=speaker_attribute,
        )

    async def _inference_loop(self) -> None:
        while True:
            item = await self._inference_queue.get()

            if item is _STOP:
                return

            if not isinstance(item, SpeakerWindow):
                continue

            started = time.perf_counter()

            try:
                uid = await self._resolve_speaker(item)

                if uid is not None and (item.window_index - 1) % self._attribute_every == 0:
                    await self._infer_attribute(item, uid)

                duration = time.perf_counter() - started

                if duration > self._step_sec:
                    logger.warning(
                        "Speaker inference is falling behind "
                        "duration=%.3fs interval=%.3fs queue_size=%s "
                        "source_id=%s generation=%s window_index=%s",
                        duration,
                        self._step_sec,
                        self._inference_queue.qsize(),
                        item.source.source_id,
                        item.source.source_generation,
                        item.window_index,
                    )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Speaker window inference failed source_id=%s generation=%s segment_id=%s window_index=%s",
                    item.source.source_id,
                    item.source.source_generation,
                    item.segment.segment_id if item.segment else None,
                    item.window_index,
                )

    """Perception consumer"""

    async def _consume_loop(self) -> None:
        while True:
            try:
                await self.perception_runtime.wait_for_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={PerceptionStreamKind.SPEECH},
                )
                window = self.perception_runtime.take_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={PerceptionStreamKind.SPEECH},
                    require_payload=True,
                )

                if window.has_gap:
                    logger.warning(
                        "Persona Speaker observed speech gap missed=%s",
                        window.missed_count,
                    )
                    self._sources.clear()

                for observation in window.speech_frames:
                    frame = self._extract_frame(observation)
                    if frame is not None:
                        self._append_frame(observation, frame)

                self.perception_runtime.commit_observations(window)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Persona Speaker failed to consume speech observations")
                await asyncio.sleep(0.05)

    """Runtime operations"""

    async def start(self) -> None:
        if self._started:
            return

        self._started = True

        self._inference_task = asyncio.create_task(
            self._inference_loop(),
            name="persona_speaker_inference",
        )
        self._consume_task = asyncio.create_task(
            self._consume_loop(),
            name="persona_speaker_consumer",
        )

        logger.info(
            "Persona Speaker started "
            "sample_rate=%s window_samples=%s step_samples=%s "
            "step_sec=%.2f attribute_interval_sec=%.2f queue_size=%s",
            self._sample_rate,
            self._window_samples,
            self._step_samples,
            self._step_sec,
            self.ATTRIBUTE_INTERVAL_SEC,
            self._inference_queue.maxsize,
        )

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False

        if self._consume_task is not None:
            self._consume_task.cancel()
            await asyncio.gather(self._consume_task, return_exceptions=True)
            self._consume_task = None

        if self._inference_task is not None:
            self._inference_task.cancel()
            await asyncio.gather(self._inference_task, return_exceptions=True)
            self._inference_task = None

        self._sources.clear()
        self.perception_runtime.clear_observation_consumer(
            self.CONSUMER_ID,
            streams={PerceptionStreamKind.SPEECH},
        )

        logger.info("Persona Speaker stopped")
