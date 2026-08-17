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

from collections.abc import Iterable
from dataclasses import replace

from alphaavatar.core.time import RuntimeTime

from .enum import (
    MediaModality,
    MediaSourceKind,
)
from .schema import (
    MediaSourceSnapshot,
    MediaSourceStateEvent,
    PerceptionEvent,
)


class MediaSourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[tuple[str, int], MediaSourceSnapshot] = {}

    def apply(
        self,
        event: MediaSourceStateEvent,
        *,
        sequence: int,
        at: RuntimeTime,
    ) -> MediaSourceSnapshot:
        key = event.source_id, event.generation
        previous = self._sources.get(key)
        metadata = dict(previous.metadata) if previous else {}
        metadata.update(event.metadata)
        snapshot = MediaSourceSnapshot(
            source_id=event.source_id,
            generation=event.generation,
            modality=event.modality,
            source_kind=event.source_kind,
            state=event.state,
            changed_at=at,
            changed_sequence=sequence,
            latest_observation_at=previous.latest_observation_at if previous else None,
            latest_observation_sequence=previous.latest_observation_sequence if previous else None,
            metadata=metadata,
        )
        self._sources[key] = snapshot
        return snapshot

    def observe(
        self,
        *,
        source_id: str,
        generation: int,
        sequence: int,
        at: RuntimeTime,
    ) -> MediaSourceSnapshot | None:
        key = source_id, generation
        source = self._sources.get(key)
        if source is None:
            return None
        source = replace(
            source,
            latest_observation_at=at,
            latest_observation_sequence=sequence,
        )
        self._sources[key] = source
        return source

    def get(self, source_id: str, generation: int) -> MediaSourceSnapshot | None:
        return self._sources.get((source_id, generation))

    def snapshot(
        self,
        *,
        modality: MediaModality | None = None,
        source_kind: MediaSourceKind | None = None,
    ) -> tuple[MediaSourceSnapshot, ...]:
        sources = (
            source
            for source in self._sources.values()
            if (modality is None or source.modality == modality)
            and (source_kind is None or source.source_kind == source_kind)
        )
        return _effective_sources(sources)

    def clear(self) -> None:
        self._sources.clear()


def _source_sort_key(source: MediaSourceSnapshot) -> tuple[str, str, str, int]:
    return source.modality.value, source.source_kind.value, source.source_id, source.generation


def _effective_sources(states: Iterable[MediaSourceSnapshot]) -> tuple[MediaSourceSnapshot, ...]:
    latest: dict[tuple[MediaModality, MediaSourceKind, str], MediaSourceSnapshot] = {}
    for state in states:
        key = state.modality, state.source_kind, state.source_id
        current = latest.get(key)
        if current is None or (state.generation, state.changed_sequence) > (
            current.generation,
            current.changed_sequence,
        ):
            latest[key] = state
    return tuple(sorted(latest.values(), key=_source_sort_key))


def advance_source_states(
    states: Iterable[MediaSourceSnapshot],
    events: Iterable[PerceptionEvent],
) -> tuple[MediaSourceSnapshot, ...]:
    current = {source.key: source for source in states}
    for event in sorted(events, key=lambda item: item.sequence):
        source_event = event.source_state
        if source_event is not None:
            key = source_event.source_id, source_event.generation
            previous = current.get(key)
            metadata = dict(previous.metadata) if previous else {}
            metadata.update(source_event.metadata)
            current[key] = MediaSourceSnapshot(
                source_id=source_event.source_id,
                generation=source_event.generation,
                modality=source_event.modality,
                source_kind=source_event.source_kind,
                state=source_event.state,
                changed_at=event.time_range.end,
                changed_sequence=event.sequence,
                latest_observation_at=previous.latest_observation_at if previous else None,
                latest_observation_sequence=previous.latest_observation_sequence
                if previous
                else None,
                metadata=metadata,
            )
            continue

        observation = event.observation
        if observation is None:
            continue
        generation = observation.metadata.get("source_generation")
        if not isinstance(generation, int):
            continue
        key = observation.source_id, generation
        source = current.get(key)
        if source is not None:
            current[key] = replace(
                source,
                latest_observation_at=observation.time_range.end,
                latest_observation_sequence=event.sequence,
            )

    return _effective_sources(current.values())
