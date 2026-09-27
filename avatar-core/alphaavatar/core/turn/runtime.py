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

import asyncio
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from alphaavatar.core.env import EnvObservation
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.time import RuntimeTime

from .schema import TurnEntityRef, TurnInputModality, TurnSnapshot
from .stream import TurnStream


class TurnRuntime:
    def __init__(
        self,
        *,
        perception: PerceptionRuntime,
        max_snapshots: int = 128,
        event_maxlen: int = 256,
        context_ready_timeout_sec: float = 0.5,
    ) -> None:
        if max_snapshots <= 0:
            raise ValueError("max_snapshots must be positive")
        if context_ready_timeout_sec < 0:
            raise ValueError("context_ready_timeout_sec cannot be negative")

        self._perception = perception
        self._max_snapshots = max_snapshots
        self._context_ready_timeout_sec = context_ready_timeout_sec
        self._snapshots: OrderedDict[str, TurnSnapshot] = OrderedDict()
        self._event_sequences: dict[str, int] = {}
        self._context_consumers: set[str] = set()
        self._last_cutoff = perception.capture_cutoff()

        self.events = TurnStream(session_id=perception.session_id, maxlen=event_maxlen)

    @property
    def latest(self) -> TurnSnapshot | None:
        return next(reversed(self._snapshots.values()), None)

    @property
    def perception(self) -> PerceptionRuntime:
        return self._perception

    def get(self, input_id: str) -> TurnSnapshot | None:
        return self._snapshots.get(input_id)

    def _record(self, snapshot: TurnSnapshot) -> TurnSnapshot:
        self._snapshots[snapshot.input_id] = snapshot
        event = self.events.publish(snapshot)
        self._event_sequences[snapshot.turn_id] = event.sequence
        self._last_cutoff = snapshot.cutoff

        while len(self._snapshots) > self._max_snapshots:
            _, removed = self._snapshots.popitem(last=False)
            self._event_sequences.pop(removed.turn_id, None)

        return snapshot

    def commit_input(
        self,
        *,
        input_id: str,
        modality: TurnInputModality,
        text: str | None = None,
        input_observation_ids: Sequence[str] = (),
        final_observations: Sequence[EnvObservation] = (),
        actors: Sequence[TurnEntityRef] = (),
        addressees: Sequence[TurnEntityRef] = (),
        context_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> TurnSnapshot:
        if not input_id:
            raise ValueError("input_id cannot be empty")

        if existing := self._snapshots.get(input_id):
            return existing

        observation_ids = tuple(
            dict.fromkeys(
                (
                    *input_observation_ids,
                    *(observation.observation_id for observation in final_observations),
                )
            )
        )

        start_cutoff = self._last_cutoff
        perception = self._perception.capture_snapshot(
            after_sequence=start_cutoff.sequence,
            final_observations=final_observations,
        )

        snapshot = TurnSnapshot(
            turn_id=uuid4().hex,
            input_id=input_id,
            modality=modality,
            text=text,
            input_observation_ids=observation_ids,
            started_at=start_cutoff.captured_at,
            committed_at=perception.cutoff.captured_at,
            start_cutoff=start_cutoff,
            cutoff=perception.cutoff,
            perception_events=perception.events,
            perception_gap=perception.has_gap,
            missed_perception_events=perception.missed_count,
            actors=tuple(actors),
            addressees=tuple(addressees),
            context_ids=tuple(dict.fromkeys(context_ids)),
            metadata=MappingProxyType(dict(metadata or {})),
        )

        self._record(snapshot)
        return snapshot

    def commit_event_input(
        self,
        *,
        input_id: str,
        modality: TurnInputModality,
        text: str | None,
        started_at: RuntimeTime,
        committed_at: RuntimeTime,
        cutoff_sequence: int,
        input_observation_ids: Sequence[str] = (),
        actors: Sequence[TurnEntityRef] = (),
        addressees: Sequence[TurnEntityRef] = (),
        context_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> TurnSnapshot:
        if not input_id:
            raise ValueError("input_id cannot be empty")

        if existing := self._snapshots.get(input_id):
            return existing

        start_cutoff = self._last_cutoff
        perception = self._perception.capture_snapshot_until(
            after_cutoff=start_cutoff,
            until_sequence=cutoff_sequence,
            captured_at=committed_at,
        )

        snapshot = TurnSnapshot(
            turn_id=uuid4().hex,
            input_id=input_id,
            modality=modality,
            text=text,
            input_observation_ids=tuple(dict.fromkeys(input_observation_ids)),
            started_at=started_at,
            committed_at=committed_at,
            start_cutoff=start_cutoff,
            cutoff=perception.cutoff,
            perception_events=perception.events,
            perception_gap=perception.has_gap,
            missed_perception_events=perception.missed_count,
            actors=tuple(actors),
            addressees=tuple(addressees),
            context_ids=tuple(dict.fromkeys(context_ids)),
            metadata=MappingProxyType(dict(metadata or {})),
        )

        self._record(snapshot)
        return snapshot

    def register_context_consumer(self, consumer_id: str) -> None:
        if not consumer_id:
            raise ValueError("consumer_id cannot be empty")
        self._context_consumers.add(consumer_id)

    def unregister_context_consumer(self, consumer_id: str) -> None:
        self._context_consumers.discard(consumer_id)

    async def wait_context_ready(
        self,
        snapshot: TurnSnapshot,
        *,
        timeout: float | None = None,
    ) -> bool:
        consumers = tuple(self._context_consumers)
        if not consumers:
            return True

        sequence = self._event_sequences.get(snapshot.turn_id)
        if sequence is None:
            return True

        timeout = self._context_ready_timeout_sec if timeout is None else timeout
        if timeout < 0:
            raise ValueError("timeout cannot be negative")
        if timeout == 0:
            return False

        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(
                    *(
                        self.events.wait_until_consumed(
                            consumer_id=consumer_id,
                            cursor_seq=sequence,
                        )
                        for consumer_id in consumers
                    )
                )
            return True
        except TimeoutError:
            return False

    def clear(self) -> None:
        self._snapshots.clear()
        self._event_sequences.clear()
        self.events.clear()
        self._last_cutoff = self._perception.capture_cutoff()
