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

from .stream import PerceptionStream


def _timestamp_sort_key(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        pass

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


@dataclass(slots=True)
class PerceptionWindow:
    consumer_id: str
    observations: list[EnvObservation] = field(default_factory=list)
    stream_cursors: dict[str, int] = field(default_factory=dict)

    def by_kind(
        self,
        *kinds: str,
    ) -> list[EnvObservation]:
        accepted = set(kinds)

        return [observation for observation in self.observations if observation.kind in accepted]

    @property
    def video_frames(self) -> list[EnvObservation]:
        return self.by_kind(
            "video_frame",
            "screen_frame",
        )

    @property
    def audio_segments(self) -> list[EnvObservation]:
        return self.by_kind("audio_segment")


class PerceptionWindowBuilder:
    def __init__(
        self,
        *,
        streams: dict[
            str,
            PerceptionStream[EnvObservation],
        ],
    ) -> None:
        self._streams = streams

    def take_pending(
        self,
        *,
        consumer_id: str,
        streams: set[str],
        require_payload: bool = False,
        min_age_sec: float = 0.0,
        limit_per_stream: int | None = None,
    ) -> PerceptionWindow:
        observations: list[EnvObservation] = []
        cursors: dict[str, int] = {}

        for stream_name in streams:
            stream = self._streams.get(stream_name)
            if stream is None:
                raise ValueError(f"Unknown perception stream: {stream_name!r}")

            result = stream.read_pending(
                consumer_id=consumer_id,
                predicate=((lambda obs: obs.has_payload) if require_payload else None),
                min_age_sec=min_age_sec,
                limit=limit_per_stream,
            )

            observations.extend(result.items)
            cursors[stream_name] = result.cursor_seq

        observations.sort(key=lambda observation: _timestamp_sort_key(observation.timestamp))

        return PerceptionWindow(
            consumer_id=consumer_id,
            observations=observations,
            stream_cursors=cursors,
        )

    def commit(
        self,
        window: PerceptionWindow,
    ) -> None:
        for stream_name, cursor_seq in window.stream_cursors.items():
            stream = self._streams.get(stream_name)
            if stream is None:
                continue

            stream.commit(
                consumer_id=window.consumer_id,
                cursor_seq=cursor_seq,
            )
