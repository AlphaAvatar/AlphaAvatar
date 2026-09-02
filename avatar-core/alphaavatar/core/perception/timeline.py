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

import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock

from alphaavatar.core.env import EnvAnnotation, EnvObservation, ObservationKind

EnvAnnotationRenderer = Callable[[EnvObservation, EnvAnnotation], None]


@dataclass(slots=True, frozen=True)
class PendingAnnotation:
    annotation: EnvAnnotation
    target_key: str
    expires_monotonic: float


class PerceptionTimeline:
    """
    Short-lived observation/annotation alignment index.

    Timeline retains references only long enough for asynchronous annotations
    to find their target. It is not a media history store. Different
    observation kinds therefore use independent retention limits.

    Rendering always happens outside the timeline lock.
    """

    def __init__(
        self,
        *,
        max_observations: int = 256,
        retention_by_kind: Mapping[ObservationKind, int] | None = None,
        pending_annotation_ttl_sec: float = 5.0,
        max_pending_annotations: int = 512,
    ) -> None:
        if max_observations <= 0:
            raise ValueError("max_observations must be positive")
        if pending_annotation_ttl_sec <= 0:
            raise ValueError("pending_annotation_ttl_sec must be positive")
        if max_pending_annotations <= 0:
            raise ValueError("max_pending_annotations must be positive")

        self._default_retention = max_observations

        self._retention_by_kind = {}
        if retention_by_kind:
            for kind, limit in retention_by_kind.items():
                if limit < 0:
                    raise ValueError(f"Retention limit cannot be negative: kind={kind!r}")
                self._retention_by_kind[kind] = limit

        self._pending_annotation_ttl_sec = pending_annotation_ttl_sec
        self._max_pending_annotations = max_pending_annotations

        self._observations_by_id: dict[str, EnvObservation] = {}
        self._observation_id_by_frame_id: dict[str, str] = {}
        self._observation_order_by_kind: dict[str, deque[str]] = {}

        self._pending_annotations: deque[PendingAnnotation] = deque()
        self._pending_annotation_ids: set[str] = set()

        self._renderers: list[EnvAnnotationRenderer] = []
        self._lock = RLock()

    @property
    def observation_count(self) -> int:
        with self._lock:
            return len(self._observations_by_id)

    @property
    def pending_annotation_count(self) -> int:
        with self._lock:
            return len(self._pending_annotations)

    def _retention_limit(self, kind: ObservationKind) -> int:
        return self._retention_by_kind.get(kind, self._default_retention)

    def _remove_observation_locked(self, observation_id: str) -> EnvObservation | None:
        observation = self._observations_by_id.pop(observation_id, None)
        if observation is None:
            return None

        frame_id = observation.frame_id
        if frame_id and self._observation_id_by_frame_id.get(frame_id) == observation_id:
            self._observation_id_by_frame_id.pop(frame_id, None)

        return observation

    def _evict_kind_locked(self, kind: ObservationKind) -> None:
        order = self._observation_order_by_kind.get(kind)
        if order is None:
            return

        limit = self._retention_limit(kind)

        while len(order) > limit:
            self._remove_observation_locked(order.popleft())

        if not order:
            self._observation_order_by_kind.pop(kind, None)

    def _prune_pending_locked(self, now: float) -> None:
        while self._pending_annotations:
            pending = self._pending_annotations[0]

            if (
                pending.expires_monotonic > now
                and len(self._pending_annotations) <= self._max_pending_annotations
            ):
                break

            removed = self._pending_annotations.popleft()
            self._pending_annotation_ids.discard(removed.annotation.annotation_id)

    def _store_pending_locked(self, annotation: EnvAnnotation, now: float) -> bool:
        target_key = annotation.target_key
        if target_key is None or annotation.annotation_id in self._pending_annotation_ids:
            return False

        self._prune_pending_locked(now)

        while len(self._pending_annotations) >= self._max_pending_annotations:
            removed = self._pending_annotations.popleft()
            self._pending_annotation_ids.discard(removed.annotation.annotation_id)

        self._pending_annotations.append(
            PendingAnnotation(
                annotation=annotation,
                target_key=target_key,
                expires_monotonic=now + self._pending_annotation_ttl_sec,
            )
        )
        self._pending_annotation_ids.add(annotation.annotation_id)
        return True

    def _take_pending_locked(self, observation: EnvObservation, now: float) -> list[EnvAnnotation]:
        self._prune_pending_locked(now)

        target_keys = {f"observation:{observation.observation_id}"}
        if observation.frame_id:
            target_keys.add(f"frame:{observation.frame_id}")

        matched: list[EnvAnnotation] = []
        remaining: deque[PendingAnnotation] = deque()

        while self._pending_annotations:
            pending = self._pending_annotations.popleft()

            if pending.target_key in target_keys:
                matched.append(pending.annotation)
                self._pending_annotation_ids.discard(pending.annotation.annotation_id)
            else:
                remaining.append(pending)

        self._pending_annotations = remaining
        return matched

    def _find_observation_locked(self, annotation: EnvAnnotation) -> EnvObservation | None:
        if annotation.observation_id:
            observation = self._observations_by_id.get(annotation.observation_id)
            if observation is not None:
                return observation

        if annotation.frame_id:
            observation_id = self._observation_id_by_frame_id.get(annotation.frame_id)
            if observation_id:
                return self._observations_by_id.get(observation_id)

        return None

    def attach_annotation(
        self,
        annotation: EnvAnnotation,
    ) -> tuple[EnvObservation | None, bool]:
        with self._lock:
            observation = self._find_observation_locked(annotation)

            if observation is None:
                return None, self._store_pending_locked(annotation, time.monotonic())

            return observation, observation.add_annotation(annotation)

    def render_annotation(
        self,
        observation: EnvObservation,
        annotation: EnvAnnotation,
    ) -> None:
        with self._lock:
            renderers = tuple(self._renderers)

        for renderer in renderers:
            renderer(observation, annotation)

    def add_observation(self, observation: EnvObservation) -> None:
        render_jobs: list[tuple[EnvAnnotationRenderer, EnvObservation, EnvAnnotation]] = []

        with self._lock:
            now = time.monotonic()
            existing = self._observations_by_id.get(observation.observation_id)

            if existing is not None:
                old_frame_id = existing.frame_id
                if (
                    old_frame_id
                    and old_frame_id != observation.frame_id
                    and self._observation_id_by_frame_id.get(old_frame_id)
                    == observation.observation_id
                ):
                    self._observation_id_by_frame_id.pop(old_frame_id, None)

                if existing.kind != observation.kind:
                    old_order = self._observation_order_by_kind.get(existing.kind)
                    if old_order is not None:
                        try:
                            old_order.remove(observation.observation_id)
                        except ValueError:
                            pass
            else:
                order = self._observation_order_by_kind.setdefault(observation.kind, deque())
                order.append(observation.observation_id)

            if existing is not None and existing.kind != observation.kind:
                self._observation_order_by_kind.setdefault(observation.kind, deque()).append(
                    observation.observation_id
                )

            self._observations_by_id[observation.observation_id] = observation

            if observation.frame_id:
                self._observation_id_by_frame_id[observation.frame_id] = observation.observation_id

            pending = self._take_pending_locked(observation, now)
            renderers = tuple(self._renderers)

            for annotation in pending:
                if not observation.add_annotation(annotation):
                    continue

                render_jobs.extend((renderer, observation, annotation) for renderer in renderers)

            self._evict_kind_locked(observation.kind)

        for renderer, target, annotation in render_jobs:
            renderer(target, annotation)

    def add_annotation(self, annotation: EnvAnnotation) -> EnvObservation | None:
        observation, added = self.attach_annotation(annotation)
        if added and observation is not None:
            self.render_annotation(observation, annotation)
        return observation

    def add_renderer(self, renderer: EnvAnnotationRenderer) -> None:
        with self._lock:
            if renderer not in self._renderers:
                self._renderers.append(renderer)

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
                target_id = self._observation_id_by_frame_id.get(frame_id)
                return self._observations_by_id.get(target_id) if target_id else None

            return None

    def remove_renderer(self, renderer: EnvAnnotationRenderer) -> None:
        with self._lock:
            if renderer in self._renderers:
                self._renderers.remove(renderer)

    def clear(self) -> None:
        with self._lock:
            self._observations_by_id.clear()
            self._observation_id_by_frame_id.clear()
            self._observation_order_by_kind.clear()
            self._pending_annotations.clear()
            self._pending_annotation_ids.clear()
