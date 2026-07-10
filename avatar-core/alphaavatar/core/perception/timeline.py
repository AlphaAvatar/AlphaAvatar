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

from collections import deque
from collections.abc import Callable
from threading import RLock

from alphaavatar.core.env import EnvAnnotation, EnvObservation

EnvAnnotationRenderer = Callable[
    [EnvObservation, EnvAnnotation],
    None,
]


class PerceptionTimeline:
    """
    Observation/annotation alignment index.

    Heavy annotation rendering always happens outside the timeline lock.
    """

    def __init__(
        self,
        *,
        max_observations: int = 1024,
    ) -> None:
        self._max_observations = max_observations

        self._observations_by_id: dict[
            str,
            EnvObservation,
        ] = {}

        self._observations_by_frame_id: dict[
            str,
            EnvObservation,
        ] = {}

        self._observation_order: deque[str] = deque()

        self._pending_annotations: dict[
            str,
            list[EnvAnnotation],
        ] = {}

        self._renderers: list[EnvAnnotationRenderer] = []
        self._lock = RLock()

    def add_renderer(
        self,
        renderer: EnvAnnotationRenderer,
    ) -> None:
        with self._lock:
            if renderer not in self._renderers:
                self._renderers.append(renderer)

    def remove_renderer(
        self,
        renderer: EnvAnnotationRenderer,
    ) -> None:
        with self._lock:
            if renderer in self._renderers:
                self._renderers.remove(renderer)

    def _evict_oldest_if_needed(self) -> None:
        while len(self._observation_order) >= self._max_observations:
            oldest_id = self._observation_order.popleft()
            oldest = self._observations_by_id.pop(
                oldest_id,
                None,
            )

            if oldest is None:
                continue

            frame_id = oldest.frame_id
            if frame_id and self._observations_by_frame_id.get(frame_id) is oldest:
                self._observations_by_frame_id.pop(
                    frame_id,
                    None,
                )

    def add_observation(
        self,
        observation: EnvObservation,
    ) -> None:
        render_jobs: list[
            tuple[
                EnvAnnotationRenderer,
                EnvObservation,
                EnvAnnotation,
            ]
        ] = []

        with self._lock:
            if observation.observation_id not in self._observations_by_id:
                self._evict_oldest_if_needed()
                self._observation_order.append(observation.observation_id)

            self._observations_by_id[observation.observation_id] = observation

            if observation.frame_id:
                self._observations_by_frame_id[observation.frame_id] = observation

            pending = self._pending_annotations.pop(
                observation.observation_id,
                [],
            )

            renderers = tuple(self._renderers)

            for annotation in pending:
                if not observation.add_annotation(annotation):
                    continue

                for renderer in renderers:
                    render_jobs.append(
                        (
                            renderer,
                            observation,
                            annotation,
                        )
                    )

        for renderer, target, annotation in render_jobs:
            renderer(target, annotation)

    def get_observation(
        self,
        *,
        observation_id: str | None = None,
        frame_id: str | None = None,
    ) -> EnvObservation | None:
        with self._lock:
            if observation_id:
                return self._observations_by_id.get(observation_id)

            if frame_id:
                return self._observations_by_frame_id.get(frame_id)

            return None

    def add_annotation(
        self,
        annotation: EnvAnnotation,
    ) -> EnvObservation | None:
        renderers: tuple[EnvAnnotationRenderer, ...] = ()
        observation: EnvObservation | None = None
        should_render = False

        with self._lock:
            observation = self._observations_by_id.get(annotation.observation_id)

            if observation is None and annotation.frame_id:
                observation = self._observations_by_frame_id.get(annotation.frame_id)

            if observation is None:
                self._pending_annotations.setdefault(
                    annotation.observation_id,
                    [],
                ).append(annotation)

                return None

            should_render = observation.add_annotation(annotation)
            if should_render:
                renderers = tuple(self._renderers)

        if should_render:
            for renderer in renderers:
                renderer(observation, annotation)

        return observation
