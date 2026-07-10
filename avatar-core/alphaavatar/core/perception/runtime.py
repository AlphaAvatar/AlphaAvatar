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

from alphaavatar.core.env import EnvAnnotation, EnvObservation

from .stream import PerceptionStream, StreamRead
from .timeline import EnvAnnotationRenderer, PerceptionTimeline
from .window import PerceptionWindow, PerceptionWindowBuilder


class PerceptionRuntime:
    """
    Session-scoped full-duplex perception runtime.

    Runtime relation:
        SessionRuntime
        ContextRuntime
        PerceptionRuntime

    These are parallel runtime components.
    """

    def __init__(
        self,
        *,
        session_id: str,
    ) -> None:
        self.session_id = session_id

        self.video = PerceptionStream[EnvObservation](
            name="video",
            maxlen=256,
        )

        self.audio = PerceptionStream[EnvObservation](
            name="audio",
            maxlen=512,
        )

        self.screen = PerceptionStream[EnvObservation](
            name="screen",
            maxlen=128,
        )

        self.events = PerceptionStream[EnvObservation](
            name="events",
            maxlen=512,
        )

        self.annotations = PerceptionStream[EnvAnnotation](
            name="annotations",
            maxlen=1024,
        )

        self.timeline = PerceptionTimeline(
            max_observations=1024,
        )

        self.window_builder = PerceptionWindowBuilder(
            streams={
                "video": self.video,
                "audio": self.audio,
                "screen": self.screen,
                "events": self.events,
            }
        )

    def add_annotation_renderer(
        self,
        renderer: EnvAnnotationRenderer,
    ) -> None:
        self.timeline.add_renderer(renderer)

    def remove_annotation_renderer(
        self,
        renderer: EnvAnnotationRenderer,
    ) -> None:
        self.timeline.remove_renderer(renderer)

    def publish_observation(
        self,
        observation: EnvObservation,
    ) -> int:
        self.timeline.add_observation(observation)

        if observation.kind == "video_frame":
            return self.video.publish(observation)

        if observation.kind == "screen_frame":
            return self.screen.publish(observation)

        if observation.kind == "audio_segment":
            return self.audio.publish(observation)

        return self.events.publish(observation)

    def publish_annotation(
        self,
        annotation: EnvAnnotation,
    ) -> EnvObservation | None:
        observation = self.timeline.add_annotation(annotation)
        self.annotations.publish(annotation)
        return observation

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

    def commit_observations(
        self,
        window: PerceptionWindow,
    ) -> None:
        self.window_builder.commit(window)

    def take_pending_annotations(
        self,
        *,
        consumer_id: str,
        min_age_sec: float = 0.0,
        limit: int | None = None,
    ) -> StreamRead[EnvAnnotation]:
        return self.annotations.read_pending(
            consumer_id=consumer_id,
            min_age_sec=min_age_sec,
            limit=limit,
        )

    def commit_annotations(
        self,
        *,
        consumer_id: str,
        cursor_seq: int,
    ) -> None:
        self.annotations.commit(
            consumer_id=consumer_id,
            cursor_seq=cursor_seq,
        )
