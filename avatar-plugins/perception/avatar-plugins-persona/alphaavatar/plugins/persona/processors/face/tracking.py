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

from collections import Counter
from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSourceRef

from .config import FaceConfig


@dataclass(slots=True)
class _Track:
    entity: PerceptionEntityRef
    vector: np.ndarray | None
    seen_at: float
    generated: bool


class FaceTracks:
    """Bounded, source-local entity association; user identity remains a Session decision."""

    def __init__(self, config: FaceConfig) -> None:
        self._config = config
        self._tracks: dict[tuple[PerceptionSourceRef, str], _Track] = {}
        self._sources: dict[str, tuple[int, float]] = {}
        self._retired: list[tuple[PerceptionSourceRef, PerceptionEntityRef]] = []

    def _remove(self, key: tuple[PerceptionSourceRef, str]) -> None:
        track = self._tracks.pop(key)
        if track.generated:
            self._retired.append((key[0], track.entity))

    def activate(self, source: PerceptionSourceRef) -> bool:
        current = self._sources.get(source.source_id)
        if current is not None and source.source_generation < current[0]:
            return False
        if current is None and len(self._sources) >= self._config.max_tracks:
            return False
        if current is None or source.source_generation > current[0]:
            for key in tuple(self._tracks):
                if key[0].source_id == source.source_id:
                    self._remove(key)
            self._sources[source.source_id] = (source.source_generation, float("-inf"))
        return True

    def current(self, source: PerceptionSourceRef) -> bool:
        current = self._sources.get(source.source_id)
        return current is not None and current[0] == source.source_generation

    def associate(
        self,
        source: PerceptionSourceRef,
        vectors: list[np.ndarray | None],
        explicit: list[PerceptionEntityRef | None],
        *,
        at: float,
    ) -> tuple[PerceptionEntityRef | None, ...]:
        if len(vectors) != len(explicit):
            raise ValueError("Face vectors and entity references must have the same length")

        result: list[PerceptionEntityRef | None] = [None] * len(vectors)
        if not self.current(source) or at < self._sources[source.source_id][1]:
            return tuple(result)

        self._sources[source.source_id] = (source.source_generation, at)
        for key, track in tuple(self._tracks.items()):
            if at - track.seen_at > self._config.track_ttl_sec:
                self._remove(key)

        counts = Counter(entity.entity_id for entity in explicit if entity is not None)
        for index, entity in enumerate(explicit):
            if entity is None or counts[entity.entity_id] != 1:
                continue

            key = source, entity.entity_id
            track, vector = self._tracks.get(key), vectors[index]
            if track is not None:
                if (
                    vector is not None
                    and track.vector is not None
                    and (
                        vector.shape != track.vector.shape
                        or float(vector @ track.vector) < self._config.track_match_threshold
                    )
                ):
                    continue

                track.seen_at = at
                if track.vector is None and vector is not None:
                    track.vector = vector.copy()
            elif len(self._tracks) < self._config.max_tracks:
                self._tracks[key] = _Track(
                    entity, vector.copy() if vector is not None else None, at, False
                )
            else:
                continue

            result[index] = entity

        tracks = tuple(track for key, track in self._tracks.items() if key[0] == source)
        proposals: dict[int, _Track] = {}
        novel: list[int] = []
        for index, vector in enumerate(vectors):
            if explicit[index] is not None or vector is None:
                continue

            scores = sorted(
                (
                    (float(vector @ track.vector), offset)
                    for offset, track in enumerate(tracks)
                    if track.vector is not None and track.vector.shape == vector.shape
                ),
                reverse=True,
            )
            if scores and scores[0][0] >= self._config.track_match_threshold:
                if (
                    len(scores) == 1
                    or scores[0][0] - scores[1][0] >= self._config.track_match_margin
                ):
                    proposals[index] = tracks[scores[0][1]]
            else:
                novel.append(index)

        claimed = Counter(entity.entity_id for entity in result if entity is not None)
        claimed.update(track.entity.entity_id for track in proposals.values())
        for index, track in proposals.items():
            if claimed[track.entity.entity_id] == 1:
                track.seen_at = at
                result[index] = track.entity

        for index in novel:
            vector = vectors[index]
            # Similar detections in one frame cannot establish two independent identities.
            if any(
                other != index
                and vectors[other].shape == vector.shape
                and float(vector @ vectors[other]) >= self._config.track_match_threshold
                for other in novel
            ):
                continue
            if len(self._tracks) >= self._config.max_tracks:
                break

            entity = PerceptionEntityRef(entity_id=f"face-{uuid4().hex}")
            self._tracks[source, entity.entity_id] = _Track(entity, vector.copy(), at, True)
            result[index] = entity

        return tuple(result)

    def drain_retired(self) -> tuple[tuple[PerceptionSourceRef, PerceptionEntityRef], ...]:
        retired, self._retired = tuple(self._retired), []
        return retired

    def clear(self) -> None:
        for key in tuple(self._tracks):
            self._remove(key)
        self._sources.clear()
