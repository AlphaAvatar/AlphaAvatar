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
"""Lightweight output timeline retention."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from alphaavatar.core.media import AudioFrame

from .schema import OutputEvent, OutputKind, OutputLane


class OutputTimeline:
    """
    Retain lightweight output history for alignment and observability.

    Raw audio bytes are not retained. Audio events are converted to metadata
    receipts before being appended.
    """

    def __init__(self, *, max_items: int = 4096) -> None:
        if max_items <= 0:
            raise ValueError("OutputTimeline max_items must be positive")

        self._items: deque[OutputEvent] = deque(maxlen=max_items)
        self._lock = asyncio.Lock()

    async def append(self, event: OutputEvent) -> None:
        timeline_event = self._to_timeline_event(event)

        async with self._lock:
            self._items.append(timeline_event)

    async def snapshot(
        self,
        *,
        after_sequence: int | None = None,
        kinds: Iterable[OutputKind] | None = None,
        lanes: Iterable[OutputLane] | None = None,
    ) -> tuple[OutputEvent, ...]:
        kind_filter = set(kinds) if kinds is not None else None
        lane_filter = set(lanes) if lanes is not None else None

        async with self._lock:
            items = tuple(self._items)

        return tuple(
            event
            for event in items
            if (after_sequence is None or event.sequence > after_sequence)
            and (kind_filter is None or event.kind in kind_filter)
            and (lane_filter is None or event.lane in lane_filter)
        )

    @staticmethod
    def _to_timeline_event(event: OutputEvent) -> OutputEvent:
        if event.kind != OutputKind.AUDIO_FRAME:
            return event

        frame = event.payload
        if not isinstance(frame, AudioFrame):
            return event

        audio_receipt: dict[str, Any] = {
            "sample_rate": frame.sample_rate,
            "num_channels": frame.num_channels,
            "samples_per_channel": frame.samples_per_channel,
            "duration_sec": (
                frame.samples_per_channel / frame.sample_rate if frame.sample_rate > 0 else 0.0
            ),
        }

        return replace(
            event,
            payload=audio_receipt,
        )
