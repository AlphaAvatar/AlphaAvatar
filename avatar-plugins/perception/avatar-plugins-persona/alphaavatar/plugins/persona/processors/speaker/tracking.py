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

from alphaavatar.agents.runtime.modules.participants.schemas import EntityId
from alphaavatar.agents.utils.vector import WeightedMean
from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSourceRef


@dataclass(slots=True)
class SpeakerTrack:
    entity: PerceptionEntityRef
    voice: WeightedMean
    sources: list[PerceptionSourceRef]  # Every source and generation it was heard on, in order


class SpeakerTracks:
    """The session's voices; matching a user never selects a track. A track's voice is every
    segment it took, each by the seconds its vector is from. A voice is matched on any source
    and generation, keeps each it was heard on, and lasts until the processor stops: the same
    speaker after a pause, a new generation or on another device stays its entity when the
    voice matches. Tracks are not bounded here; participant capacity bounds their entities."""

    def __init__(self, *, threshold: float, margin: float) -> None:
        self.threshold, self.margin = threshold, margin
        self._tracks: dict[EntityId, SpeakerTrack] = {}
        self._retired: list[PerceptionEntityRef] = []

    def resolve(
        self, source: PerceptionSourceRef, vector: np.ndarray, seconds: float
    ) -> PerceptionEntityRef | None:
        ranked = sorted(
            (
                (float(np.dot(track.voice.vector, vector)), entity_id)
                for entity_id, track in self._tracks.items()
                if track.voice.total.shape == vector.shape
            ),
            reverse=True,
        )
        if ranked and ranked[0][0] >= self.threshold:
            # Within the margin of the next track, a tie included, it is neither's.
            if len(ranked) > 1 and ranked[0][0] - ranked[1][0] <= self.margin:
                return None

            track = self._tracks[ranked[0][1]]
            track.voice.add(vector, seconds)
            if source not in track.sources:
                track.sources.append(source)
            return track.entity

        entity = PerceptionEntityRef(f"speaker-{uuid4().hex}")
        self._tracks[entity.entity_id] = SpeakerTrack(
            entity, WeightedMean.of(vector, seconds), [source]
        )
        return entity

    def clear(self) -> None:
        self._retired.extend(track.entity for track in self._tracks.values())
        self._tracks.clear()

    def drain_retired(self) -> tuple[PerceptionEntityRef, ...]:
        retired = tuple(self._retired)
        self._retired.clear()
        return retired
