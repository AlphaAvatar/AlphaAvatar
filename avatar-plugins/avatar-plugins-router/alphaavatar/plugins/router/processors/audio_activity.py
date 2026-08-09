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

from alphaavatar.agents.avatar.voice import VADBase
from alphaavatar.agents.interaction import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import (
    AudioFrame,
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
)

from ..log import logger
from .audio_activity_source import AudioActivitySource


class AudioActivityProcessor(RouterProcessorBase):
    CONSUMER_ID = "router.audio_activity"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        vad: VADBase,
        pre_roll_sec: float = 0.15,
        max_buffer_sec: float = 2.0,
    ) -> None:
        super().__init__(runtime=runtime)

        self._vad = vad
        self._pre_roll_sec = pre_roll_sec
        self._max_buffer_sec = max_buffer_sec
        self._sources: dict[str, AudioActivitySource] = {}
        self._task: asyncio.Task[None] | None = None
        self._started = False

    @property
    def name(self) -> str:
        return "audio_activity"

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

    def _create_source(
        self,
        observation: EnvObservation,
        frame: AudioFrame,
    ) -> AudioActivitySource:
        source = AudioActivitySource(
            perception_runtime=self._runtime.perception,
            source_id=observation.source_id,
            vad=self._vad,
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            pre_roll_sec=self._pre_roll_sec,
            max_buffer_sec=self._max_buffer_sec,
        )

        self._sources[observation.source_id] = source
        return source

    async def _replace_source(
        self,
        observation: EnvObservation,
        frame: AudioFrame,
    ) -> AudioActivitySource:
        previous = self._sources.pop(observation.source_id, None)

        if previous is not None:
            await previous.close(graceful=False)

        return self._create_source(observation, frame)

    async def _consume_observation(self, observation: EnvObservation) -> None:
        frame = self._extract_frame(observation)

        if frame is None:
            return

        source = self._sources.get(observation.source_id)

        if source is None:
            source = self._create_source(observation, frame)
        elif source.failed or not source.matches(frame):
            source = await self._replace_source(observation, frame)

        if source.push(observation, frame):
            return

        source = await self._replace_source(observation, frame)

        if not source.push(observation, frame):
            logger.error(
                "Audio Activity dropped frame source_id=%s observation_id=%s",
                observation.source_id,
                observation.observation_id,
            )

    async def _close_sources(self, *, graceful: bool) -> None:
        sources = list(self._sources.values())
        self._sources.clear()

        for source in sources:
            await source.close(graceful=graceful)

    async def _consume_loop(self) -> None:
        while True:
            try:
                await self._runtime.perception.wait_for_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={"audio"},
                )

                window = self._runtime.perception.take_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={"audio"},
                    require_payload=True,
                )

                if window.has_gap:
                    logger.warning(
                        "Audio Activity input gap missed=%s",
                        window.missed_count,
                    )
                    await self._close_sources(graceful=False)

                for observation in window.audio_frames:
                    await self._consume_observation(observation)

                self._runtime.perception.commit_observations(window)

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception("Audio Activity failed to consume observations")
                await asyncio.sleep(0.05)

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        self._task = asyncio.create_task(
            self._consume_loop(),
            name="router_audio_activity",
        )

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False

        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

        await self._close_sources(graceful=True)
        self._runtime.perception.clear_consumer(
            self.CONSUMER_ID,
            streams={"audio"},
        )
