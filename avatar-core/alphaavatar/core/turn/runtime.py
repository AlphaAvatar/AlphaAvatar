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
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from math import isfinite
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from alphaavatar.core.env import EnvObservation
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.time import RuntimeTime

from .enums import TurnInputModality
from .schemas import TurnEntityRef, TurnSnapshot
from .stream import TurnStream

logger = logging.getLogger(__name__)


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
        if not isfinite(context_ready_timeout_sec) or context_ready_timeout_sec < 0:
            raise ValueError("context_ready_timeout_sec must be finite and nonnegative")

        self._perception = perception
        self._max_snapshots = max_snapshots
        self._context_ready_timeout_sec = context_ready_timeout_sec
        self._snapshots: OrderedDict[str, TurnSnapshot] = OrderedDict()
        self._event_sequences: dict[str, int] = {}
        self._context_consumers: set[str] = set()
        self._context_waiters: dict[str, Callable[[TurnSnapshot], Awaitable[None]]] = {}
        self._context_changed = asyncio.Event()
        self._context_pending: dict[str, dict[str, int]] = {}
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

    """Commit op"""

    def _record(self, snapshot: TurnSnapshot) -> TurnSnapshot:
        self._snapshots[snapshot.input_id] = snapshot
        event = self.events.publish(snapshot)
        self._event_sequences[snapshot.turn_id] = event.sequence
        self._last_cutoff = snapshot.cutoff

        while len(self._snapshots) > self._max_snapshots:
            _, removed = self._snapshots.popitem(last=False)
            self._event_sequences.pop(removed.turn_id, None)

        self._perception.input_trace.record(
            "turn.committed",
            turn_id=snapshot.turn_id,
            input_id=snapshot.input_id,
            candidate_revision=snapshot.metadata.get("candidate_revision"),
            decision_id=snapshot.metadata.get("decision_annotation_id"),
            event_id=snapshot.metadata.get("decision_event_id"),
            sequence=snapshot.metadata.get("decision_event_sequence"),
            start_cutoff_sequence=snapshot.start_cutoff.sequence,
            cutoff_sequence=snapshot.cutoff.sequence,
            evidence_count=len(snapshot.input_observation_ids),
            missed_count=snapshot.missed_perception_events,
            text_chars=len(snapshot.text) if isinstance(snapshot.text, str) else 0,
        )
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
            after_sequence=start_cutoff.sequence, final_observations=final_observations
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
            after_cutoff=start_cutoff, until_sequence=cutoff_sequence, captured_at=committed_at
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

    """Context op"""

    def _notify_context_changed(self) -> None:
        previous, self._context_changed = self._context_changed, asyncio.Event()
        previous.set()

    def register_context_consumer(
        self, consumer_id: str, *, waiter: Callable[[TurnSnapshot], Awaitable[None]] | None = None
    ) -> None:
        """A waiter joins consumer-owned work and owns its bounded completion policy."""
        if not consumer_id:
            raise ValueError("consumer_id cannot be empty")
        if waiter is not None and not callable(waiter):
            raise TypeError("context waiter must be callable")
        self._context_consumers.add(consumer_id)
        if waiter is None:
            self._context_waiters.pop(consumer_id, None)
        else:
            self._context_waiters[consumer_id] = waiter
        self._notify_context_changed()

    def unregister_context_consumer(self, consumer_id: str) -> None:
        self._context_consumers.discard(consumer_id)
        self._context_waiters.pop(consumer_id, None)
        self._notify_context_changed()

    async def _wait_context_cursors(self, snapshot: TurnSnapshot, timeout: float) -> bool:
        sequence = self._event_sequences.get(snapshot.turn_id)
        if sequence is None:
            return True

        def pending() -> tuple[str, ...]:
            return tuple(
                consumer_id
                for consumer_id in self._context_consumers - self._context_waiters.keys()
                if self.events.consumer_cursor(consumer_id) < sequence
            )

        if not pending():
            return True
        if timeout == 0:
            return False

        try:
            async with asyncio.timeout(timeout):
                while consumers := pending():
                    changed = asyncio.create_task(self._context_changed.wait())
                    consumed = asyncio.gather(
                        *(
                            self.events.wait_until_consumed(
                                consumer_id=consumer_id, cursor_seq=sequence
                            )
                            for consumer_id in consumers
                        )
                    )
                    try:
                        await asyncio.wait((consumed, changed), return_when=asyncio.FIRST_COMPLETED)
                        if consumed.done():
                            await consumed
                    finally:
                        consumed.cancel()
                        changed.cancel()
                        await asyncio.gather(consumed, changed, return_exceptions=True)
            return True
        except TimeoutError:
            return not pending()

    def pending_context_consumers(self, snapshot: TurnSnapshot) -> tuple[str, ...]:
        sequence = self._event_sequences.get(snapshot.turn_id)
        pending = set(self._context_pending.get(snapshot.turn_id, ()))
        if sequence is not None:
            pending.update(
                consumer_id
                for consumer_id in self._context_consumers - self._context_waiters.keys()
                if self.events.consumer_cursor(consumer_id) < sequence
            )
        return tuple(sorted(pending))

    async def _wait_context_consumer(
        self,
        consumer_id: str,
        waiter: Callable[[TurnSnapshot], Awaitable[None]],
        snapshot: TurnSnapshot,
    ) -> bool:
        pending = self._context_pending.setdefault(snapshot.turn_id, {})
        pending[consumer_id] = pending.get(consumer_id, 0) + 1

        async def join() -> None:
            await waiter(snapshot)

        work = asyncio.create_task(join(), name=f"turn_context:{consumer_id}:{snapshot.turn_id}")
        try:
            while self._context_waiters.get(consumer_id) is waiter:
                if self.get(snapshot.input_id) is not snapshot:
                    return False
                changed = asyncio.create_task(self._context_changed.wait())
                try:
                    await asyncio.wait((work, changed), return_when=asyncio.FIRST_COMPLETED)
                    if work.done():
                        await work
                        return True
                finally:
                    changed.cancel()
                    await asyncio.gather(changed, return_exceptions=True)
            return True
        except Exception as error:
            logger.warning(
                "Turn context consumer failed consumer_id=%s turn_id=%s error_type=%s",
                consumer_id,
                snapshot.turn_id,
                type(error).__name__,
            )
            return False
        finally:
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            pending[consumer_id] -= 1
            if not pending[consumer_id]:
                del pending[consumer_id]
            if not pending:
                self._context_pending.pop(snapshot.turn_id, None)

    async def _wait_registered_context(self, snapshot: TurnSnapshot, cursor_timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + cursor_timeout
        while True:
            if self.get(snapshot.input_id) is not snapshot:
                return False
            generation = self._context_changed
            changed = asyncio.create_task(generation.wait(), name="turn_context_registration")
            tasks = {
                asyncio.create_task(
                    self._wait_context_cursors(
                        snapshot, max(0.0, deadline - asyncio.get_running_loop().time())
                    ),
                    name=f"turn_context_cursors:{snapshot.turn_id}",
                ),
                *(
                    asyncio.create_task(
                        self._wait_context_consumer(consumer_id, waiter, snapshot),
                        name=f"turn_context_waiter:{consumer_id}:{snapshot.turn_id}",
                    )
                    for consumer_id, waiter in tuple(self._context_waiters.items())
                ),
            }
            try:
                pending = tasks
                while pending:
                    done, _ = await asyncio.wait(
                        (*pending, changed), return_when=asyncio.FIRST_COMPLETED
                    )
                    if generation.is_set():
                        break
                    failed = [task.get_name() for task in done if not task.result()]
                    if failed:
                        logger.debug(
                            "Turn context not ready turn_id=%s failed=%s pending=%s",
                            snapshot.turn_id,
                            failed,
                            self.pending_context_consumers(snapshot),
                        )
                        return False
                    pending -= done
                else:
                    return True
            except asyncio.CancelledError:
                logger.debug(
                    "Turn context wait interrupted turn_id=%s pending=%s",
                    snapshot.turn_id,
                    self.pending_context_consumers(snapshot),
                )
                raise
            finally:
                changed.cancel()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(changed, *tasks, return_exceptions=True)
            # Registration changes restart only join wrappers; consumers retain work ownership.

    async def wait_context_ready(
        self, snapshot: TurnSnapshot, *, timeout: float | None = None
    ) -> bool:
        if timeout is not None and (not isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be finite and nonnegative")
        if not self._context_consumers:
            return True

        # The default budget covers canonical cursors; registered work owns its own deadline.
        # An explicit caller timeout caps the entire join without cancelling consumer-owned work.
        try:
            async with asyncio.timeout(timeout):
                return await self._wait_registered_context(
                    snapshot, self._context_ready_timeout_sec
                )
        except TimeoutError:
            return False

    def clear(self) -> None:
        self._snapshots.clear()
        self._event_sequences.clear()
        self.events.clear()
        self._notify_context_changed()
        self._last_cutoff = self._perception.capture_cutoff()
