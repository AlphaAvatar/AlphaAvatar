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
"""Bounded diagnostic retention without PCM buffers or invalid stream payloads."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable

from .enums import OutputKind, OutputLane
from .schemas import OutputEvent, OutputIdentity
from .schemas.timeline import OutputAudioSummary, OutputTimelineEntry


class OutputTimeline:
    def __init__(self, *, max_items: int = 4096) -> None:
        if type(max_items) is not int or max_items <= 0:
            raise ValueError("OutputTimeline max_items must be positive")
        self._items: deque[OutputTimelineEntry] = deque(maxlen=max_items)
        self._lock = asyncio.Lock()

    async def append(self, event: OutputEvent) -> None:
        output = event.output
        content = output
        if output.kind == OutputKind.AUDIO_FRAME:
            frame = output.payload
            content = OutputAudioSummary(
                OutputIdentity(output.output_id, output.lane, output.scope),
                output.source,
                frame.sample_rate,
                frame.num_channels,
                frame.samples_per_channel,
                frame.sample_format,
                output.metadata,
            )
        entry = OutputTimelineEntry(
            event.event_id,
            event.sequence,
            event.session_id,
            event.created_at,
            event.monotonic_ns,
            content,
        )
        async with self._lock:
            self._items.append(entry)

    async def snapshot(
        self,
        *,
        after_sequence: int | None = None,
        kinds: Iterable[OutputKind] | None = None,
        lanes: Iterable[OutputLane] | None = None,
    ) -> tuple[OutputTimelineEntry, ...]:
        kind_filter = set(kinds) if kinds is not None else None
        lane_filter = set(lanes) if lanes is not None else None

        async with self._lock:
            items = tuple(self._items)

        result = []
        for entry in items:
            content = entry.content
            audio = isinstance(content, OutputAudioSummary)
            kind = OutputKind.AUDIO_FRAME if audio else content.kind
            lane = content.identity.lane if audio else content.lane
            if (
                (after_sequence is None or entry.sequence > after_sequence)
                and (kind_filter is None or kind in kind_filter)
                and (lane_filter is None or lane in lane_filter)
            ):
                result.append(entry)
        return tuple(result)
