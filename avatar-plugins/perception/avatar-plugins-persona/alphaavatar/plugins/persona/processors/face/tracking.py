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

from alphaavatar.agents.runtime.modules.participants.schemas import EntityId
from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSourceRef


@dataclass(slots=True)
class FaceTrack:
    entity: PerceptionEntityRef
    vector: np.ndarray
    sources: list[PerceptionSourceRef]  # Every source and generation it was seen on, in order


class FaceTracks:
    """The session's faces; matching a user never selects a track. A face is matched on any
    source and generation, keeps each it was seen on, and lasts until the processor stops: the
    same face after a long absence, a new generation or on another camera stays its entity.
    Tracks are not bounded here; participant capacity bounds their entities. Which generation
    of a source is current is ParticipantRuntime's, and the processor's sampling keeps its
    frames in order."""

    def __init__(self, *, threshold: float, margin: float) -> None:
        self.threshold = threshold
        self.margin = margin

        self._tracks: dict[EntityId, FaceTrack] = {}
        self._retired: list[PerceptionEntityRef] = []

    @staticmethod
    def _seen(track: FaceTrack, source: PerceptionSourceRef) -> PerceptionEntityRef:
        if source not in track.sources:
            track.sources.append(source)
        return track.entity

    def resolve(
        self, source: PerceptionSourceRef, vectors: list[np.ndarray | None]
    ) -> tuple[PerceptionEntityRef | None, ...]:
        """One frame's faces, in order: each the entity of the session face it matches, a new
        one, or none for a face without a vector or between two."""
        result: list[PerceptionEntityRef | None] = [None] * len(vectors)
        # Every face of the session is a candidate, whatever source or generation it was seen on.
        tracks = tuple(self._tracks.values())
        proposals: dict[int, FaceTrack] = {}
        novel: list[int] = []
        for index, vector in enumerate(vectors):
            if vector is None:
                continue

            scores = sorted(
                (
                    (float(vector @ track.vector), offset)
                    for offset, track in enumerate(tracks)
                    if track.vector.shape == vector.shape
                ),
                reverse=True,
            )
            if scores and scores[0][0] >= self.threshold:
                if len(scores) == 1 or scores[0][0] - scores[1][0] >= self.margin:
                    proposals[index] = tracks[scores[0][1]]
            else:
                novel.append(index)

        # One frame shows each face once: a track two of its faces claim is neither's.
        claimed = Counter(track.entity.entity_id for track in proposals.values())
        for index, track in proposals.items():
            if claimed[track.entity.entity_id] == 1:
                result[index] = self._seen(track, source)

        for index in novel:
            vector = vectors[index]
            # Similar detections in one frame cannot establish two independent identities.
            if any(
                other != index
                and vectors[other].shape == vector.shape
                and float(vector @ vectors[other]) >= self.threshold
                for other in novel
            ):
                continue

            entity = PerceptionEntityRef(entity_id=f"face-{uuid4().hex}")
            self._tracks[entity.entity_id] = FaceTrack(entity, vector.copy(), [source])
            result[index] = entity

        return tuple(result)

    def drain_retired(self) -> tuple[PerceptionEntityRef, ...]:
        retired, self._retired = tuple(self._retired), []
        return retired

    def clear(self) -> None:
        self._retired.extend(track.entity for track in self._tracks.values())
        self._tracks.clear()
