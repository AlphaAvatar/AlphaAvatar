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
from collections.abc import Sequence
from threading import RLock
from typing import Any

from alphaavatar.core.env import EnvAnnotation, EnvObservation, ObservationKind
from alphaavatar.core.time import RuntimeClock, RuntimeTime, RuntimeTimeRange

from .event import (
    MediaModality,
    MediaSourceKind,
    MediaSourceSnapshot,
    MediaSourceStateEvent,
    PerceptionCutoff,
    PerceptionEvent,
    PerceptionEventKind,
    PerceptionSnapshot,
)
from .source_registry import MediaSourceRegistry
from .stream import PerceptionStream
from .timeline import EnvAnnotationRenderer, PerceptionTimeline
from .window import PerceptionWindow, PerceptionWindowBuilder


class PerceptionRuntime:
    """Session-scoped full-duplex perception runtime."""

    _STREAM_BY_OBSERVATION_KIND = {
        ObservationKind.VIDEO_FRAME: "video",
        ObservationKind.VIDEO_CLIP: "video",
        ObservationKind.SCREEN_FRAME: "screen",
        ObservationKind.AUDIO_FRAME: "audio",
        ObservationKind.AUDIO_SEGMENT: "audio",
        ObservationKind.SPEECH_FRAME: "speech",
        ObservationKind.SPEECH_SEGMENT: "speech",
        ObservationKind.TRANSCRIPT_DELTA: "text",
        ObservationKind.TRANSCRIPT_SEGMENT: "text",
        ObservationKind.TEXT_INPUT: "text",
    }

    _STREAM_MAXLEN = {
        "video": 512,
        "screen": 256,
        "audio": 1024,
        "speech": 1024,
        "text": 1024,
        "event": 8192,
    }

    _TIMELINE_RETENTION_BY_KIND = {
        ObservationKind.VIDEO_FRAME: 256,
        ObservationKind.SCREEN_FRAME: 128,
        ObservationKind.VIDEO_CLIP: 32,
        ObservationKind.AUDIO_SEGMENT: 64,
        ObservationKind.SPEECH_SEGMENT: 64,
        ObservationKind.TRANSCRIPT_SEGMENT: 128,
        ObservationKind.TEXT_INPUT: 128,
        ObservationKind.IMAGE_INPUT: 64,
    }

    _EVENT_EXCLUDED_OBSERVATION_KINDS = {
        # AUDIO_FRAME intentionally remains in events so Realtime consumers and
        # ENV Memory can build time-aligned continuous audio windows.
        ObservationKind.SPEECH_FRAME,
        ObservationKind.TRANSCRIPT_DELTA,
    }

    _TIMELINE_EXCLUDED_OBSERVATION_KINDS = {
        ObservationKind.AUDIO_FRAME,
        ObservationKind.SPEECH_FRAME,
        ObservationKind.TRANSCRIPT_DELTA,
    }

    def __init__(
        self,
        *,
        session_id: str,
        clock: RuntimeClock | None = None,
    ) -> None:
        if not session_id:
            raise ValueError("session_id cannot be empty")

        self.session_id = session_id
        self.clock = clock or RuntimeClock()

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

        # Text
        self.text = PerceptionStream[EnvObservation](
            name="text", maxlen=self._STREAM_MAXLEN["text"]
        )

        # Session-level Events
        self.events = PerceptionStream[PerceptionEvent](
            name="events", maxlen=self._STREAM_MAXLEN["event"]
        )

        self._observation_streams = {
            "video": self.video,
            "screen": self.screen,
            "audio": self.audio,
            "speech": self.speech,
            "text": self.text,
        }

        self.timeline = PerceptionTimeline(
            max_observations=256,
            retention_by_kind=self._TIMELINE_RETENTION_BY_KIND,
            pending_annotation_ttl_sec=5.0,
            max_pending_annotations=512,
        )
        self.window_builder = PerceptionWindowBuilder(streams=self._observation_streams)

        self._event_sequence = 0
        self._source_registry = MediaSourceRegistry()
        self._lock = RLock()

        # speech active event
        self._active_speech_segments: set[tuple[str, str]] = set()
        self._speech_idle_event = asyncio.Event()
        self._speech_idle_event.set()
        self._last_speech_idle_cutoff = self._capture_cutoff_locked()

    @property
    def latest_event_sequence(self) -> int:
        with self._lock:
            return self._event_sequence

    @property
    def has_active_speech(self) -> bool:
        with self._lock:
            return bool(self._active_speech_segments)

    @property
    def active_speech_segments(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            return tuple(sorted(self._active_speech_segments))

    @staticmethod
    def _speech_segment_key(
        observation: EnvObservation,
    ) -> tuple[str, str] | None:
        if observation.kind not in {
            ObservationKind.SPEECH_FRAME,
            ObservationKind.SPEECH_SEGMENT,
        }:
            return None

        segment_id = getattr(observation, "segment_id", None) or observation.metadata.get(
            "segment_id"
        )

        if not segment_id:
            return None

        return observation.source_id, str(segment_id)

    def _update_speech_activity_locked(
        self,
        observation: EnvObservation,
    ) -> None:
        key = self._speech_segment_key(observation)

        if key is None:
            return

        if observation.kind == ObservationKind.SPEECH_FRAME:
            if key in self._active_speech_segments:
                return

            if not self._active_speech_segments:
                # Replace the event instead of clearing it. Existing waiters keep
                # waiting on the event belonging to their current speech period.
                self._speech_idle_event = asyncio.Event()

            self._active_speech_segments.add(key)
            return

        was_active = bool(self._active_speech_segments)
        self._active_speech_segments.discard(key)

        if was_active and not self._active_speech_segments:
            # SPEECH_SEGMENT has already entered the global event stream when this
            # method runs, so the cutoff includes the complete segment boundary.
            self._last_speech_idle_cutoff = self._capture_cutoff_locked()
            self._speech_idle_event.set()

    def _publish_event_locked(
        self,
        *,
        kind: PerceptionEventKind,
        payload: EnvObservation | MediaSourceStateEvent,
        time_range: RuntimeTimeRange,
    ) -> PerceptionEvent:
        self._event_sequence += 1
        event = PerceptionEvent(
            session_id=self.session_id,
            sequence=self._event_sequence,
            time_range=time_range,
            kind=kind,
            payload=payload,
        )

        sequence = self.events.publish(event)
        if sequence != event.sequence:
            raise RuntimeError(
                f"Perception event sequence diverged: stream={sequence}, session={event.sequence}"
            )

        return event

    def _publish_observation_locked(self, observation: EnvObservation) -> PerceptionEvent | None:
        stream_name = self._STREAM_BY_OBSERVATION_KIND.get(observation.kind)

        if stream_name is not None:
            self._observation_streams[stream_name].publish(observation)

        event: PerceptionEvent | None = None

        if observation.kind not in self._EVENT_EXCLUDED_OBSERVATION_KINDS:
            event = self._publish_event_locked(
                kind=PerceptionEventKind.OBSERVATION,
                payload=observation,
                time_range=observation.time_range,
            )

            generation = observation.metadata.get("source_generation")

            if isinstance(generation, int):
                self._source_registry.observe(
                    source_id=observation.source_id,
                    generation=generation,
                    sequence=event.sequence,
                    at=observation.time_range.end,
                )

        self._update_speech_activity_locked(observation)
        return event

    def _add_to_timeline(self, observations: Sequence[EnvObservation]) -> None:
        for observation in observations:
            if observation.kind not in self._TIMELINE_EXCLUDED_OBSERVATION_KINDS:
                self.timeline.add_observation(observation)

    """Annotation operations"""

    def add_annotation_renderer(self, renderer: EnvAnnotationRenderer) -> None:
        self.timeline.add_renderer(renderer)

    def remove_annotation_renderer(self, renderer: EnvAnnotationRenderer) -> None:
        self.timeline.remove_renderer(renderer)

    def publish_annotation(self, annotation: EnvAnnotation) -> EnvObservation | None:
        return self.timeline.add_annotation(annotation)

    """Cutoff operations"""

    def _capture_cutoff_locked(self) -> PerceptionCutoff:
        return PerceptionCutoff(
            sequence=self._event_sequence,
            captured_at=self.clock.now(),
            sources=self._source_registry.snapshot(),
        )

    def capture_cutoff(self) -> PerceptionCutoff:
        with self._lock:
            return self._capture_cutoff_locked()

    def capture_snapshot(
        self,
        *,
        after_sequence: int,
        final_observations: Sequence[EnvObservation] = (),
    ) -> PerceptionSnapshot:
        """
        Atomically publish final direct inputs and freeze one immutable event range.

        No producer using this runtime can insert an event between final_observations
        and the returned cutoff.
        """
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")

        final_observations = tuple(final_observations)
        with self._lock:
            for observation in final_observations:
                self._publish_observation_locked(observation)

            cutoff = self._capture_cutoff_locked()
            if after_sequence > cutoff.sequence:
                raise ValueError(
                    "after_sequence cannot exceed current perception event sequence: "
                    f"after_sequence={after_sequence}, current={cutoff.sequence}"
                )
            event_slice = self.events.read_range(
                after_seq=after_sequence, until_seq=cutoff.sequence
            )

        self._add_to_timeline(final_observations)
        return PerceptionSnapshot(
            after_sequence=after_sequence,
            cutoff=cutoff,
            events=event_slice.items,
            first_available_sequence=event_slice.first_available_seq,
            missed_count=event_slice.missed_count,
        )

    """Speech active operations"""

    def capture_cutoff_if_speech_idle(self) -> PerceptionCutoff | None:
        """
        Atomically check speech activity and capture a cutoff.

        A speech segment cannot start between the idle check and the cutoff.
        """
        with self._lock:
            if self._active_speech_segments:
                return None

            return self._capture_cutoff_locked()

    async def wait_for_speech_idle_cutoff(
        self,
        *,
        timeout: float | None = None,
    ) -> PerceptionCutoff | None:
        """
        Wait for the next boundary at which all active speech segments are closed.

        The returned cutoff was captured atomically when the final active
        SPEECH_SEGMENT was published.
        """
        with self._lock:
            if not self._active_speech_segments:
                return self._capture_cutoff_locked()

            event = self._speech_idle_event

        try:
            if timeout is None:
                await event.wait()
            else:
                await asyncio.wait_for(
                    event.wait(),
                    timeout=timeout,
                )
        except TimeoutError:
            return None

        with self._lock:
            return self._last_speech_idle_cutoff

    """Source state operations"""

    def publish_source_state(
        self,
        source_state: MediaSourceStateEvent,
        *,
        at: RuntimeTime | None = None,
    ) -> PerceptionEvent:
        occurred_at = at or self.clock.now()
        with self._lock:
            event = self._publish_event_locked(
                kind=PerceptionEventKind.SOURCE_STATE,
                payload=source_state,
                time_range=RuntimeTimeRange.point(occurred_at),
            )
            self._source_registry.apply(source_state, sequence=event.sequence, at=occurred_at)

        return event

    def get_source_states(
        self,
        *,
        modality: MediaModality | None = None,
        source_kind: MediaSourceKind | None = None,
    ) -> tuple[MediaSourceSnapshot, ...]:
        with self._lock:
            return self._source_registry.snapshot(modality=modality, source_kind=source_kind)

    """Observation operations"""

    def _get_observation_streams(
        self, names: set[str]
    ) -> tuple[PerceptionStream[EnvObservation], ...]:
        if not names:
            raise ValueError("At least one perception stream is required")
        unknown = names.difference(self._observation_streams)
        if unknown:
            raise ValueError(f"Unknown perception stream(s): {', '.join(sorted(unknown))}")
        return tuple(self._observation_streams[name] for name in sorted(names))

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
                stream.wait_for_pending(consumer_id=consumer_id, min_age_sec=min_age_sec),
                name=f"perception_wait:{consumer_id}:{stream.name}",
            )
            for stream in streams
        ]

        try:
            done, _ = await asyncio.wait(
                tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            return bool(done) and any(task.result() for task in done)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

    def publish_observation(self, observation: EnvObservation) -> PerceptionEvent | None:
        with self._lock:
            event = self._publish_observation_locked(observation)

        self._add_to_timeline((observation,))
        return event

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

    def clear_consumer(self, consumer_id: str, *, streams: set[str] | None = None) -> None:
        selected = (
            self._get_observation_streams(streams)
            if streams is not None
            else tuple(self._observation_streams.values())
        )
        for stream in selected:
            stream.clear_consumer(consumer_id)
