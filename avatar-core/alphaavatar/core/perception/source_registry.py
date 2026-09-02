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

from alphaavatar.core.env import PerceptionSourceRef
from alphaavatar.core.time import RuntimeTime

from .enum import MediaModality, MediaSourceKind
from .schema import (
    MediaSourceSnapshot,
    MediaSourceStateEvent,
    PerceptionEvent,
)


class MediaSourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[PerceptionSourceRef, MediaSourceSnapshot] = {}
        self._generation_by_source: dict[str, int] = {}

    @classmethod
    def project_snapshot(
        cls,
        *,
        initial_sources: Iterable[MediaSourceSnapshot],
        events: Iterable[PerceptionEvent],
    ) -> tuple[MediaSourceSnapshot, ...]:
        registry = cls()
        registry._sources = {snapshot.source: snapshot for snapshot in initial_sources}

        for event in events:
            registry.apply_event(event)

        return registry.snapshot()

    def _apply(
        self,
        event: MediaSourceStateEvent,
        *,
        sequence: int,
        at: RuntimeTime,
    ) -> MediaSourceSnapshot:
        previous = self._sources.get(event.source)
        metadata = dict(previous.metadata) if previous else {}
        metadata.update(event.metadata)

        snapshot = MediaSourceSnapshot(
            source=event.source,
            modality=event.modality,
            source_kind=event.source_kind,
            state=event.state,
            changed_at=at,
            changed_sequence=sequence,
            transport_participant_id=event.transport_participant_id,
            latest_observation_at=(previous.latest_observation_at if previous else None),
            latest_observation_sequence=(
                previous.latest_observation_sequence if previous else None
            ),
            metadata=metadata,
        )
        self._sources[event.source] = snapshot
        return snapshot

    def _observe(
        self,
        *,
        source: PerceptionSourceRef,
        sequence: int,
        at: RuntimeTime,
    ) -> MediaSourceSnapshot | None:
        snapshot = self._sources.get(source)
        if snapshot is None:
            return None

        snapshot = replace(
            snapshot,
            latest_observation_at=at,
            latest_observation_sequence=sequence,
        )
        self._sources[source] = snapshot
        return snapshot

    def apply_event(
        self,
        event: PerceptionEvent,
    ) -> MediaSourceSnapshot | None:
        source_state = event.source_state
        if source_state is not None:
            return self._apply(
                source_state,
                sequence=event.sequence,
                at=event.time_range.end,
            )

        observation = event.observation
        if observation is not None:
            return self._observe(
                source=observation.source,
                sequence=event.sequence,
                at=observation.time_range.end,
            )

        return None

    def snapshot(
        self,
        *,
        modality: MediaModality | None = None,
        source_kind: MediaSourceKind | None = None,
    ) -> tuple[MediaSourceSnapshot, ...]:
        states = (
            source
            for source in self._sources.values()
            if (modality is None or source.modality == modality)
            and (source_kind is None or source.source_kind == source_kind)
        )
        return _effective_sources(states)

    def get(self, source: PerceptionSourceRef) -> MediaSourceSnapshot | None:
        return self._sources.get(source)

    def next_source(self, source_id: str) -> PerceptionSourceRef:
        generation = self._generation_by_source.get(source_id, 0) + 1
        self._generation_by_source[source_id] = generation

        return PerceptionSourceRef(
            source_id=source_id,
            source_generation=generation,
        )

    def clear(self) -> None:
        self._sources.clear()


def _source_sort_key(
    state: MediaSourceSnapshot,
) -> tuple[str, str, str, int]:
    return (
        state.modality.value,
        state.source_kind.value,
        state.source_id,
        state.source_generation,
    )


def _effective_sources(
    states: Iterable[MediaSourceSnapshot],
) -> tuple[MediaSourceSnapshot, ...]:
    latest: dict[
        tuple[MediaModality, MediaSourceKind, str],
        MediaSourceSnapshot,
    ] = {}

    for state in states:
        key = state.modality, state.source_kind, state.source_id
        current = latest.get(key)

        if current is None or (
            state.source_generation,
            state.changed_sequence,
        ) > (
            current.source_generation,
            current.changed_sequence,
        ):
            latest[key] = state

    return tuple(sorted(latest.values(), key=_source_sort_key))
