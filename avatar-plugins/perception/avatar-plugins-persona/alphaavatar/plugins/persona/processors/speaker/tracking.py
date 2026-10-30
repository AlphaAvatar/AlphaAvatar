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
from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSourceRef


@dataclass(slots=True)
class SpeakerTrack:
    entity: PerceptionEntityRef
    vector: np.ndarray
    seen_at: float


class SpeakerTracks:
    """Bounded acoustic associations; matching a user never selects a track."""

    def __init__(self, *, threshold: float, margin: float, max_tracks: int, ttl_sec: float) -> None:
        self.threshold, self.margin = threshold, margin
        self.max_tracks, self.ttl_sec = max_tracks, ttl_sec
        self._tracks: dict[PerceptionSourceRef, list[SpeakerTrack]] = {}
        self._retired: list[tuple[PerceptionSourceRef, PerceptionEntityRef]] = []

    def resolve(
        self, source: PerceptionSourceRef, vector: np.ndarray, now: float
    ) -> PerceptionEntityRef | None:
        for current, tracks in tuple(self._tracks.items()):
            if (
                current.source_id == source.source_id
                and current.source_generation < source.source_generation
            ):
                self._retired.extend((current, track.entity) for track in tracks)
                self._tracks.pop(current)
            else:
                self._retired.extend(
                    (current, track.entity)
                    for track in tracks
                    if now - track.seen_at > self.ttl_sec
                )
                tracks[:] = [track for track in tracks if now - track.seen_at <= self.ttl_sec]
                if not tracks:
                    self._tracks.pop(current)

        tracks = self._tracks.setdefault(source, [])
        ranked = sorted(
            (
                (float(np.dot(track.vector, vector)), i)
                for i, track in enumerate(tracks)
                if track.vector.shape == vector.shape
            ),
            reverse=True,
        )
        if ranked and ranked[0][0] >= self.threshold:
            if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < self.margin:
                return None

            track = tracks[ranked[0][1]]
            track.seen_at = now
            return track.entity

        if sum(map(len, self._tracks.values())) >= self.max_tracks:
            return None

        entity = PerceptionEntityRef(f"speaker-{uuid4().hex}")
        tracks.append(SpeakerTrack(entity, vector.copy(), now))
        return entity

    def clear(self, source: PerceptionSourceRef | None = None) -> None:
        if source is None:
            self._retired.extend(
                (current, track.entity)
                for current, tracks in self._tracks.items()
                for track in tracks
            )
            self._tracks.clear()
        else:
            self._retired.extend((source, track.entity) for track in self._tracks.pop(source, ()))

    def drain_retired(self) -> tuple[tuple[PerceptionSourceRef, PerceptionEntityRef], ...]:
        retired = tuple(self._retired)
        self._retired.clear()
        return retired
