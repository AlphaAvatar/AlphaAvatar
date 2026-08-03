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
"""Live asynchronous output stream with control-message priority."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterable

from .schema import OutputControl, OutputControlType, OutputEvent, OutputKind, OutputLane

OutputPredicate = Callable[[OutputEvent], bool]


def _is_priority_control(event: OutputEvent) -> bool:
    control = event.payload
    return (
        event.is_control
        and isinstance(control, OutputControl)
        and control.type == OutputControlType.INTERRUPT
    )


class OutputSubscription:
    """
    One live output consumer.

    Control events have a separate priority queue so an interrupt cannot become
    trapped behind already queued audio or text chunks.
    """

    def __init__(
        self,
        *,
        name: str,
        kinds: set[OutputKind] | None,
        lanes: set[OutputLane] | None,
        max_pending: int,
        reliable: bool,
    ) -> None:
        if not name:
            raise ValueError("Output subscription requires a name")

        if max_pending <= 0:
            raise ValueError("Output subscription max_pending must be positive")

        self.name = name
        self._kinds = kinds
        self._lanes = lanes
        self._max_pending = max_pending
        self._reliable = reliable

        self._control_events: deque[OutputEvent] = deque()
        self._data_events: deque[OutputEvent] = deque()

        self._condition = asyncio.Condition()
        self._closed = False

    def accepts(self, event: OutputEvent) -> bool:
        if self._kinds is not None and event.kind not in self._kinds:
            return False

        if event.is_control:
            control = event.payload

            if isinstance(control, OutputControl):
                target_lane = control.target_lane

                # A control without a target lane may target an output_id or
                # turn_id across multiple lanes. All control-aware subscribers
                # must inspect it themselves.
                if target_lane is None:
                    return True

                if self._lanes is not None and target_lane not in self._lanes:
                    return False

                return True

        if self._lanes is not None and event.lane not in self._lanes:
            return False

        return True

    async def push(self, event: OutputEvent) -> None:
        if not self.accepts(event):
            return

        async with self._condition:
            if self._closed:
                return

            if _is_priority_control(event):
                self._control_events.append(event)
                self._condition.notify_all()
                return

            if self._reliable:
                await self._condition.wait_for(
                    lambda: (self._closed or len(self._data_events) < self._max_pending)
                )

                if self._closed:
                    return

            else:
                while len(self._data_events) >= self._max_pending:
                    self._data_events.popleft()

            self._data_events.append(event)
            self._condition.notify_all()

    async def get(self) -> OutputEvent:
        async with self._condition:
            await self._condition.wait_for(
                lambda: (self._closed or bool(self._control_events) or bool(self._data_events))
            )

            if self._control_events:
                event = self._control_events.popleft()
                self._condition.notify_all()
                return event

            if self._data_events:
                event = self._data_events.popleft()
                self._condition.notify_all()
                return event

            raise RuntimeError(f"Output subscription {self.name!r} is closed")

    async def discard_pending(
        self,
        predicate: OutputPredicate,
    ) -> int:
        async with self._condition:
            retained: deque[OutputEvent] = deque()
            discarded = 0

            while self._data_events:
                event = self._data_events.popleft()

                if predicate(event):
                    discarded += 1
                else:
                    retained.append(event)

            self._data_events = retained
            self._condition.notify_all()

            return discarded

    async def close(self) -> None:
        async with self._condition:
            if self._closed:
                return

            self._closed = True
            self._control_events.clear()
            self._data_events.clear()
            self._condition.notify_all()


class OutputStream:
    """
    Fan-out stream for live output delivery.

    Reliable subscriptions apply asynchronous backpressure. Unreliable
    subscriptions drop their oldest pending data event, but control events are
    always retained and delivered first.
    """

    def __init__(self) -> None:
        self._subscriptions: dict[str, OutputSubscription] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def subscribe(
        self,
        name: str,
        *,
        kinds: Iterable[OutputKind] | None = None,
        lanes: Iterable[OutputLane] | None = None,
        max_pending: int = 128,
        reliable: bool = True,
    ) -> OutputSubscription:
        subscription = OutputSubscription(
            name=name,
            kinds=set(kinds) if kinds is not None else None,
            lanes=set(lanes) if lanes is not None else None,
            max_pending=max_pending,
            reliable=reliable,
        )

        async with self._lock:
            if self._closed:
                raise RuntimeError("OutputStream is closed")

            if name in self._subscriptions:
                raise ValueError(f"Output subscription already exists: {name!r}")

            self._subscriptions[name] = subscription

        return subscription

    async def unsubscribe(self, name: str) -> None:
        async with self._lock:
            subscription = self._subscriptions.pop(
                name,
                None,
            )

        if subscription is not None:
            await subscription.close()

    async def publish(self, event: OutputEvent) -> None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("OutputStream is closed")

            subscriptions = tuple(self._subscriptions.values())

        if not subscriptions:
            return

        results = await asyncio.gather(
            *(subscription.push(event) for subscription in subscriptions),
            return_exceptions=True,
        )

        errors = [result for result in results if isinstance(result, Exception)]

        if errors:
            raise ExceptionGroup(
                "One or more output subscriptions failed",
                errors,
            )

    async def discard_pending(
        self,
        predicate: OutputPredicate,
    ) -> int:
        async with self._lock:
            subscriptions = tuple(self._subscriptions.values())

        if not subscriptions:
            return 0

        results = await asyncio.gather(
            *(subscription.discard_pending(predicate) for subscription in subscriptions)
        )

        return sum(results)

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return

            self._closed = True
            subscriptions = tuple(self._subscriptions.values())
            self._subscriptions.clear()

        await asyncio.gather(
            *(subscription.close() for subscription in subscriptions),
            return_exceptions=True,
        )
