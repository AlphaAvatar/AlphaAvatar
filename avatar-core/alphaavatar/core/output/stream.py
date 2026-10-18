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
from collections import deque
from collections.abc import Callable, Iterable

from alphaavatar.core.cleanup import wait_for_cleanup

from .enums import OutputControlType, OutputKind, OutputLane
from .schemas import OutputControl, OutputEvent

OutputPredicate = Callable[[OutputEvent], bool]
OutputGuard = Callable[[], bool]


def _raise_failures(message: str, results: Iterable[object]) -> None:
    errors: list[Exception] = []
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            error = RuntimeError("Output subscription cancelled itself")
            error.__cause__ = result
            errors.append(error)
        elif isinstance(result, Exception):
            errors.append(result)
        elif isinstance(result, BaseException):
            raise result
    if errors:
        raise ExceptionGroup(message, errors)


def _is_priority_control(event: OutputEvent) -> bool:
    output = event.output
    return (
        output.kind == OutputKind.CONTROL
        and isinstance(output.payload, OutputControl)
        and output.payload.type == OutputControlType.INTERRUPT
    )


class OutputSubscription:
    def __init__(
        self,
        *,
        name: str,
        kinds: set[OutputKind] | None,
        lanes: set[OutputLane] | None,
        max_pending: int,
        reliable: bool,
        control_types: frozenset[OutputControlType] | None = None,
        fail_on_overflow: bool = False,
    ) -> None:
        if not name or type(max_pending) is not int or max_pending <= 0:
            raise ValueError("Output subscription requires a name and positive capacity")
        if control_types is not None and any(
            type(kind) is not OutputControlType for kind in control_types
        ):
            raise TypeError("Control filters require OutputControlType values")
        if kinds is not None and any(type(kind) is not OutputKind for kind in kinds):
            raise TypeError("Kind filters require OutputKind values")
        if lanes is not None and any(type(lane) is not OutputLane for lane in lanes):
            raise TypeError("Lane filters require OutputLane values")

        if type(fail_on_overflow) is not bool or (fail_on_overflow and not reliable):
            raise ValueError("Fail-fast overflow requires a reliable subscription")

        self._control_types = frozenset(control_types) if control_types is not None else None
        self.name, self._kinds, self._lanes = name, kinds, lanes
        self._max_pending, self._reliable = max_pending, reliable
        self._control_events: deque[OutputEvent] = deque()
        self._data_events: deque[OutputEvent] = deque()
        self._condition = asyncio.Condition()
        self._data_lock = asyncio.Lock()
        self._closed = False
        self._fail_on_overflow = fail_on_overflow
        self.dropped_count = 0
        self._failure: Exception | None = None

    def _check_failure(self) -> None:
        if self._failure is not None:
            raise RuntimeError(f"Output subscription {self.name!r} failed") from self._failure

    def accepts(self, event: OutputEvent) -> bool:
        output = event.output
        if self._kinds is not None and output.kind not in self._kinds:
            return False
        if output.kind == OutputKind.CONTROL:
            control = output.payload
            if self._control_types is not None and control.type not in self._control_types:
                return False
            if control.type == OutputControlType.INTERRUPT:
                # Filter the immutable target set; never interpret a late broad selector.
                return self._lanes is None or any(
                    target.lane in self._lanes for target in control.targets
                )
        return self._lanes is None or output.lane in self._lanes

    async def push(self, event: OutputEvent, *, guard: OutputGuard | None = None) -> None:
        if not self.accepts(event):
            return

        if _is_priority_control(event):
            # Interrupts must bypass a full ordinary queue and its waiting publishers.
            async with self._condition:
                self._check_failure()
                if self._closed or (guard is not None and not guard()):
                    return
                self._control_events.append(event)
                self._condition.notify_all()
            return

        # Condition.wait_for releases its lock; keep the data admission slot until enqueue
        # so a new publisher cannot overtake one already waiting for queue capacity.
        async with self._data_lock, self._condition:
            self._check_failure()
            if self._closed or (guard is not None and not guard()):
                return
            if (
                self._reliable
                and self._fail_on_overflow
                and len(self._data_events) >= self._max_pending
            ):
                # Fail explicitly instead of coupling a slow presentation path to media pacing.
                self._failure = RuntimeError(f"Output subscription {self.name!r} overflowed")
                self._closed = True
                self._data_events.clear()
                self._control_events.clear()
                self._condition.notify_all()
                self._check_failure()
            if self._reliable:
                await self._condition.wait_for(
                    lambda: self._closed
                    or len(self._data_events) < self._max_pending
                    or (guard is not None and not guard())
                )
                self._check_failure()
                if self._closed:
                    return
            if guard is not None and not guard():
                return
            if not self._reliable:
                while len(self._data_events) >= self._max_pending:
                    self._data_events.popleft()
                    self.dropped_count += 1
            self._data_events.append(event)
            self._condition.notify_all()

    async def get(self) -> OutputEvent:
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._closed or bool(self._control_events) or bool(self._data_events)
            )
            self._check_failure()
            if self._control_events:
                event = self._control_events.popleft()
            elif self._data_events:
                event = self._data_events.popleft()
            else:
                raise RuntimeError(f"Output subscription {self.name!r} is closed")
            self._condition.notify_all()
            return event

    async def discard_pending(self, predicate: OutputPredicate) -> int:
        async with self._condition:
            retained = deque(event for event in self._data_events if not predicate(event))
            discarded = len(self._data_events) - len(retained)
            self._data_events = retained
            self._condition.notify_all()
            return discarded

    async def fail(self, error: Exception) -> None:
        """Retire this exact consumer without silently succeeding queued or future delivery."""
        if not isinstance(error, Exception):
            raise TypeError("Output subscription failures must be Exceptions")
        async with self._condition:
            if self._failure is None:
                self._failure = error
            self._closed = True
            self._control_events.clear()
            self._data_events.clear()
            self._condition.notify_all()

    async def close(self) -> None:
        async with self._condition:
            if self._closed:
                return
            self._closed = True
            self._control_events.clear()
            self._data_events.clear()
            self._condition.notify_all()


class OutputStream:
    """Reliable queues backpressure; unreliable queues drop oldest data, never interrupt facts."""

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
        control_types: Iterable[OutputControlType] | None = None,
        fail_on_overflow: bool = False,
    ) -> OutputSubscription:
        subscription = OutputSubscription(
            name=name,
            kinds=set(kinds) if kinds is not None else None,
            lanes=set(lanes) if lanes is not None else None,
            max_pending=max_pending,
            reliable=reliable,
            control_types=frozenset(control_types) if control_types is not None else None,
            fail_on_overflow=fail_on_overflow,
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
            subscription = self._subscriptions.pop(name, None)
        if subscription is not None:
            await subscription.close()

    async def publish(self, event: OutputEvent, *, guard: OutputGuard | None = None) -> None:
        if type(event) is not OutputEvent:
            raise TypeError("Expected OutputEvent")
        async with self._lock:
            if self._closed:
                raise RuntimeError("OutputStream is closed")
            subscriptions = tuple(self._subscriptions.values())
        if not subscriptions:
            return

        # Same one-task-per-subscriber fan-out as gather; only failure cleanup owns an extra task.
        tasks = tuple(
            asyncio.create_task(subscription.push(event, guard=guard))
            for subscription in subscriptions
        )
        pending = set(tasks)
        reported: set[asyncio.Task[None]] = set()
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                failures = [
                    asyncio.CancelledError() if task.cancelled() else task.exception()
                    for task in done
                ]
                reported = done
                _raise_failures("One or more output subscriptions failed", failures)
        except BaseException as failure:
            # Do not let a failed/self-cancelled subscriber hide behind another full queue.
            cancelled = {task for task in tasks if not task.done()}
            for task in cancelled:
                task.cancel()

            async def reap() -> None:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # Publisher-initiated cancellations are not subscriber faults.
                _raise_failures(
                    "Output fan-out cleanup failed",
                    (
                        result
                        for task, result in zip(tasks, results, strict=True)
                        if task not in reported
                        and not (task in cancelled and isinstance(result, asyncio.CancelledError))
                    ),
                )

            try:
                await wait_for_cleanup(asyncio.create_task(reap(), name="output_fanout_cleanup"))
            except BaseException as cleanup:
                raise failure from cleanup
            raise

    async def discard_pending(self, predicate: OutputPredicate) -> int:
        async with self._lock:
            subscriptions = tuple(self._subscriptions.values())
        if not subscriptions:
            return 0
        return sum(
            await asyncio.gather(
                *(subscription.discard_pending(predicate) for subscription in subscriptions)
            )
        )

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(self._subscriptions.values())
            self._subscriptions.clear()
        results = await asyncio.gather(
            *(subscription.close() for subscription in subscriptions), return_exceptions=True
        )
        _raise_failures("Output subscription cleanup failed", results)
