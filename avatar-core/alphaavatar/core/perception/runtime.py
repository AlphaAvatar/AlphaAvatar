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
from typing import Any

from alphaavatar.core.env import EnvAnnotation, EnvObservation

from .stream import PerceptionStream
from .timeline import EnvAnnotationRenderer, PerceptionTimeline
from .window import PerceptionWindow, PerceptionWindowBuilder


class PerceptionRuntime:
    """
    Session-scoped full-duplex perception runtime.

    Owns:
    - bounded multi-consumer observation streams;
    - short-lived observation/annotation alignment;
    - asynchronous consumer wake-up;
    - cursor-based observation reads.

    Does not own RTC input, inference, VAD, STT, routing, or persona policies.
    """

    _STREAM_BY_OBSERVATION_KIND = {
        "video_frame": "video",
        "screen_frame": "screen",
        "audio_frame": "audio",
        "audio_segment": "audio",
    }

    _STREAM_MAXLEN = {
        "video": 512,
        "screen": 256,
        "audio": 1024,
        "speech": 1024,
        "events": 512,
    }

    _TIMELINE_RETENTION_BY_KIND = {
        "video_frame": 256,
        "screen_frame": 128,
        "video_clip": 32,
        "audio_frame": 128,
        "audio_segment": 64,
    }

    def __init__(self, *, session_id: str) -> None:
        if not session_id:
            raise ValueError("session_id cannot be empty")

        self.session_id = session_id

        # Visual
        self.video = PerceptionStream[EnvObservation](
            name="video", maxlen=self._STREAM_MAXLEN["video"]
        )
        self.screen = PerceptionStream[EnvObservation](
            name="screen", maxlen=self._STREAM_MAXLEN["screen"]
        )

        # Voice
        self.audio = PerceptionStream[EnvObservation](
            name="audio", maxlen=self._STREAM_MAXLEN["audio"]
        )
        self.speech = PerceptionStream[EnvObservation](
            name="speech", maxlen=self._STREAM_MAXLEN["speech"]
        )

        # other
        self.events = PerceptionStream[EnvObservation](
            name="events", maxlen=self._STREAM_MAXLEN["events"]
        )

        self._observation_streams = {
            "video": self.video,
            "screen": self.screen,
            "audio": self.audio,
            "speech": self.speech,
            "events": self.events,
        }

        self.timeline = PerceptionTimeline(
            max_observations=128,
            retention_by_kind=self._TIMELINE_RETENTION_BY_KIND,
            pending_annotation_ttl_sec=5.0,
            max_pending_annotations=512,
        )
        self.window_builder = PerceptionWindowBuilder(streams=self._observation_streams)

    def _get_observation_streams(
        self, stream_names: set[str]
    ) -> tuple[PerceptionStream[EnvObservation], ...]:
        if not stream_names:
            raise ValueError("At least one perception stream is required")

        unknown = stream_names.difference(self._observation_streams)
        if unknown:
            names = ", ".join(repr(name) for name in sorted(unknown))
            raise ValueError(f"Unknown perception stream(s): {names}")

        return tuple(self._observation_streams[name] for name in sorted(stream_names))

    async def _wait_for_streams(
        self,
        *,
        consumer_id: str,
        streams: tuple[PerceptionStream[Any], ...],
        timeout: float | None,
        min_age_sec: float,
    ) -> bool:
        if len(streams) == 1:
            return await streams[0].wait_for_pending(
                consumer_id=consumer_id,
                timeout=timeout,
                min_age_sec=min_age_sec,
            )

        tasks = [
            asyncio.create_task(
                stream.wait_for_pending(
                    consumer_id=consumer_id,
                    min_age_sec=min_age_sec,
                ),
                name=f"perception_wait:{consumer_id}:{stream.name}",
            )
            for stream in streams
        ]

        try:
            done, _ = await asyncio.wait(
                tasks,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            return bool(done) and any(task.result() for task in done)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    """Annotation operations"""

    def add_annotation_renderer(self, renderer: EnvAnnotationRenderer) -> None:
        self.timeline.add_renderer(renderer)

    def remove_annotation_renderer(self, renderer: EnvAnnotationRenderer) -> None:
        self.timeline.remove_renderer(renderer)

    def publish_annotation(self, annotation: EnvAnnotation) -> EnvObservation | None:
        return self.timeline.add_annotation(annotation)

    """Observation operations"""

    def publish_observation(self, observation: EnvObservation) -> int:
        self.timeline.add_observation(observation)
        stream_name = self._STREAM_BY_OBSERVATION_KIND.get(observation.kind, "events")
        return self._observation_streams[stream_name].publish(observation)

    def publish_speech_observation(self, observation: EnvObservation) -> int:
        if observation.kind not in {"audio_frame", "audio_segment"}:
            raise ValueError(
                f"Speech stream only accepts audio_frame or audio_segment, got {observation.kind!r}"
            )

        return self.speech.publish(observation)

    async def wait_for_pending_observations(
        self,
        *,
        consumer_id: str,
        streams: set[str],
        timeout: float | None = None,
        min_age_sec: float = 0.0,
    ) -> bool:
        return await self._wait_for_streams(
            consumer_id=consumer_id,
            streams=self._get_observation_streams(streams),
            timeout=timeout,
            min_age_sec=min_age_sec,
        )

    def take_pending_observations(
        self,
        *,
        consumer_id: str,
        streams: set[str],
        require_payload: bool = False,
        min_age_sec: float = 0.0,
        limit_per_stream: int | None = None,
    ) -> PerceptionWindow:
        return self.window_builder.take_pending(
            consumer_id=consumer_id,
            streams=streams,
            require_payload=require_payload,
            min_age_sec=min_age_sec,
            limit_per_stream=limit_per_stream,
        )

    def commit_observations(self, window: PerceptionWindow) -> None:
        self.window_builder.commit(window)

    def clear_consumer(
        self,
        consumer_id: str,
        *,
        streams: set[str] | None = None,
    ) -> None:
        selected = (
            self._get_observation_streams(streams)
            if streams is not None
            else tuple(self._observation_streams.values())
        )

        for stream in selected:
            stream.clear_consumer(consumer_id)
