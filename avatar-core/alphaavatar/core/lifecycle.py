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
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from alphaavatar.core.cleanup import wait_for_cleanup

logger = logging.getLogger(__name__)


class LifecycleComponent(ABC):
    """A single-use component; on_stop must also release partial or unstarted initialization."""

    @abstractmethod
    async def on_start(self) -> None: ...

    @abstractmethod
    async def on_stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LifecyclePhase:
    name: str
    components: tuple[LifecycleComponent, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Lifecycle phase name must be nonempty")
        object.__setattr__(self, "components", tuple(self.components))

    @classmethod
    def create(cls, name: str, components: Iterable[LifecycleComponent]) -> LifecyclePhase:
        return cls(name=name, components=tuple(components))


class LifecycleError(RuntimeError):
    def __init__(self, *, action: str, phase: str, component: LifecycleComponent) -> None:
        self.action, self.phase, self.component = action, phase, component
        name = f"{type(component).__module__}.{type(component).__qualname__}"
        super().__init__(f"Failed to {action} component {name} in lifecycle phase {phase!r}")


class LifecycleGroup:
    """Own components from construction through one start/stop cycle.

    Phases are ordered; components within a phase are independent and concurrent.
    Shutdown closes every owned component, including one whose start never returned.
    """

    def __init__(self, phases: Sequence[LifecyclePhase]) -> None:
        self._phases = tuple(phases)
        self._start_requested = asyncio.Event()
        self._start_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        seen: set[int] = set()

        for phase in self._phases:
            if not isinstance(phase, LifecyclePhase):
                raise TypeError("LifecycleGroup requires LifecyclePhase objects")
            for component in phase.components:
                if not callable(getattr(component, "on_start", None)) or not callable(
                    getattr(component, "on_stop", None)
                ):
                    raise TypeError("Lifecycle components require on_start and on_stop")
                if id(component) in seen:
                    raise ValueError(f"Component {type(component).__qualname__} appears twice")
                seen.add(id(component))

    @staticmethod
    def _observe(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    @staticmethod
    async def _start_component(component: LifecycleComponent, phase: str) -> None:
        try:
            logger.debug(
                "Starting component phase=%s component=%s", phase, type(component).__qualname__
            )
            await component.on_start()
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise LifecycleError(action="start", phase=phase, component=component) from error

    async def _start(self) -> None:
        for phase in self._phases:
            async with asyncio.TaskGroup() as group:
                tasks = {
                    group.create_task(
                        self._start_component(component, phase.name),
                        name=f"component_start:{phase.name}:{type(component).__qualname__}",
                    ): component
                    for component in phase.components
                }
                pending = set(tasks)
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    # TaskGroup does not treat a child's self-cancellation as a startup failure.
                    for task in done:
                        if task.cancelled():
                            try:
                                task.result()
                            except asyncio.CancelledError as error:
                                raise LifecycleError(
                                    action="start", phase=phase.name, component=tasks[task]
                                ) from error

    async def start(self) -> None:
        if self._stop_task is not None:
            raise RuntimeError("Lifecycle group is stopping or stopped")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="lifecycle_start")
            self._start_task.add_done_callback(self._observe)
            self._start_requested.set()
        try:
            await self.wait_ready()
        except BaseException as original:
            try:
                await self.stop()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def wait_ready(self) -> None:
        await self._start_requested.wait()
        if self._stop_task is not None:
            raise RuntimeError("Lifecycle group stopped before readiness")
        task = self._start_task
        if task is None:
            raise RuntimeError("Lifecycle startup was not scheduled")
        await asyncio.shield(task)
        if self._stop_task is not None:
            raise RuntimeError("Lifecycle group stopped before readiness")

    @staticmethod
    async def _stop_component(component: LifecycleComponent, phase: str) -> None:
        try:
            logger.debug(
                "Stopping component phase=%s component=%s", phase, type(component).__qualname__
            )
            await component.on_stop()
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError
        except (asyncio.CancelledError, Exception) as error:
            raise LifecycleError(action="stop", phase=phase, component=component) from error

    async def _stop(self) -> None:
        start = self._start_task
        if start is not None:
            if not start.done() and not start.cancelling():
                start.cancel()
            await asyncio.gather(start, return_exceptions=True)
        errors: list[Exception] = []
        for phase in reversed(self._phases):
            results = await asyncio.gather(
                *(self._stop_component(component, phase.name) for component in phase.components),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    errors.append(result)
                elif isinstance(result, BaseException):
                    raise result
        if errors:
            raise ExceptionGroup("One or more lifecycle components failed to stop", errors)

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop(), name="lifecycle_stop")
            self._stop_task.add_done_callback(self._observe)
            self._start_requested.set()
        await wait_for_cleanup(self._stop_task)
