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

from dataclasses import dataclass, field
from datetime import datetime

from alphaavatar.core.env import EnvObservation

from .stream import PerceptionStream, StreamRead


def _timestamp_sort_key(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        pass

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


@dataclass(slots=True)
class PerceptionWindow:
    consumer_id: str
    observations: list[EnvObservation] = field(default_factory=list)
    stream_reads: dict[str, StreamRead[EnvObservation]] = field(default_factory=dict)

    @property
    def stream_cursors(self) -> dict[str, int]:
        return {stream_name: result.cursor_seq for stream_name, result in self.stream_reads.items()}

    def by_kind(self, *kinds: str) -> list[EnvObservation]:
        accepted = set(kinds)
        return [observation for observation in self.observations if observation.kind in accepted]

    @property
    def video_frames(self) -> list[EnvObservation]:
        return self.by_kind("video_frame", "screen_frame")

    @property
    def audio_frames(self) -> list[EnvObservation]:
        return self.by_kind("audio_frame")

    @property
    def audio_segments(self) -> list[EnvObservation]:
        return self.by_kind("audio_segment")

    @property
    def audio_observations(self) -> list[EnvObservation]:
        return self.by_kind("audio_frame", "audio_segment")

    @property
    def has_gap(self) -> bool:
        return any(result.has_gap for result in self.stream_reads.values())

    @property
    def missed_count(self) -> int:
        return sum(result.missed_count for result in self.stream_reads.values())

    @property
    def gaps(self) -> dict[str, StreamRead[EnvObservation]]:
        return {
            stream_name: result
            for stream_name, result in self.stream_reads.items()
            if result.has_gap
        }

    @property
    def committed_lag(self) -> int:
        return sum(result.committed_lag for result in self.stream_reads.values())

    @property
    def remaining_count(self) -> int:
        return sum(result.remaining_count for result in self.stream_reads.values())


class PerceptionWindowBuilder:
    def __init__(self, *, streams: dict[str, PerceptionStream[EnvObservation]]) -> None:
        self._streams = streams

    def _get_stream(self, stream_name: str) -> PerceptionStream[EnvObservation]:
        stream = self._streams.get(stream_name)
        if stream is None:
            raise ValueError(f"Unknown perception stream: {stream_name!r}")
        return stream

    def take_pending(
        self,
        *,
        consumer_id: str,
        streams: set[str],
        require_payload: bool = False,
        min_age_sec: float = 0.0,
        limit_per_stream: int | None = None,
    ) -> PerceptionWindow:
        if not streams:
            raise ValueError("At least one perception stream is required")

        observations: list[EnvObservation] = []
        reads: dict[str, StreamRead[EnvObservation]] = {}
        predicate = (lambda observation: observation.has_payload) if require_payload else None

        for stream_name in sorted(streams):
            result = self._get_stream(stream_name).read_pending(
                consumer_id=consumer_id,
                predicate=predicate,
                min_age_sec=min_age_sec,
                limit=limit_per_stream,
            )
            observations.extend(result.items)
            reads[stream_name] = result

        observations.sort(
            key=lambda observation: (
                _timestamp_sort_key(observation.timestamp),
                observation.observation_id,
            )
        )

        return PerceptionWindow(
            consumer_id=consumer_id,
            observations=observations,
            stream_reads=reads,
        )

    def commit(self, window: PerceptionWindow) -> None:
        for stream_name, result in window.stream_reads.items():
            self._get_stream(stream_name).commit(
                consumer_id=window.consumer_id,
                cursor_seq=result.cursor_seq,
            )
