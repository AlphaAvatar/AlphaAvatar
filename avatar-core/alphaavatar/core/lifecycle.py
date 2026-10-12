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
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from alphaavatar.agents.log import logger
from alphaavatar.core.cleanup import wait_for_cleanup


@dataclass(frozen=True, slots=True)
class LifecyclePhase:
    name: str
    components: tuple[LifecycleComponent, ...]

    @classmethod
    def create(
        cls,
        name: str,
        components: Iterable[LifecycleComponent],
    ) -> LifecyclePhase:
        return cls(name=name, components=tuple(components))


class LifecycleComponent(ABC):
    @abstractmethod
    async def on_start(self) -> None: ...

    @abstractmethod
    async def on_stop(self) -> None: ...


class LifecycleError(RuntimeError):
    def __init__(
        self,
        *,
        action: str,
        phase: str,
        component: LifecycleComponent,
    ) -> None:
        component_name = f"{type(component).__module__}.{type(component).__qualname__}"
        super().__init__(
            f"Failed to {action} runtime component {component_name} in lifecycle phase {phase!r}"
        )


class LifecycleGroup:
    def __init__(self, phases: Sequence[LifecyclePhase]) -> None:
        self._phases = tuple(phases)
        self._started_phases: list[LifecyclePhase] = []
        self._lock = asyncio.Lock()

        self._validate_unique_components()

    def _validate_unique_components(self) -> None:
        seen: set[int] = set()

        for phase in self._phases:
            for component in phase.components:
                component_id = id(component)
                if component_id in seen:
                    raise ValueError(
                        f"Runtime component {type(component).__qualname__} "
                        "appears in more than one lifecycle phase."
                    )
                seen.add(component_id)

    async def _start_phase(self, phase: LifecyclePhase) -> None:
        if not phase.components:
            return

        started_components: list[LifecycleComponent] = []

        async def _start_component(component: LifecycleComponent) -> None:
            try:
                logger.debug(
                    "Starting runtime component phase=%s component=%s",
                    phase.name,
                    type(component).__qualname__,
                )
                await component.on_start()
                started_components.append(component)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise LifecycleError(action="start", phase=phase.name, component=component) from exc

        try:
            async with asyncio.TaskGroup() as task_group:
                tasks = {
                    task_group.create_task(
                        _start_component(component),
                        name=f"runtime_component_start:{phase.name}:{type(component).__qualname__}",
                    ): component
                    for component in phase.components
                }
                pending = set(tasks)
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        if not task.cancelled():
                            continue
                        try:
                            task.result()
                        except asyncio.CancelledError as exc:
                            raise LifecycleError(
                                action="start", phase=phase.name, component=tasks[task]
                            ) from exc
        except BaseException:
            await wait_for_cleanup(
                asyncio.create_task(
                    self._rollback_components(
                        tuple(reversed(started_components)),
                        phase_name=f"{phase.name}:partial_start_rollback",
                    ),
                    name=f"runtime_component_rollback:{phase.name}",
                )
            )
            raise

    async def _rollback_components(
        self, components: Iterable[LifecycleComponent], *, phase_name: str
    ) -> None:
        errors = await self._stop_components(components, phase_name=phase_name, action="rollback")
        for error in errors:
            logger.error("Runtime component rollback failed: %s", error, exc_info=error)

    async def _rollback_started_phases(self) -> None:
        for phase in reversed(self._started_phases):
            await self._rollback_components(
                phase.components, phase_name=f"{phase.name}:startup_rollback"
            )
        self._started_phases.clear()

    async def _stop_components(
        self,
        components: Iterable[LifecycleComponent],
        *,
        phase_name: str,
        action: str,
    ) -> list[Exception]:
        component_list = tuple(components)
        if not component_list:
            return []

        async def _stop_component(component: LifecycleComponent) -> None:
            try:
                logger.debug(
                    "Stopping runtime component phase=%s component=%s",
                    phase_name,
                    type(component).__qualname__,
                )
                await component.on_stop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise LifecycleError(action=action, phase=phase_name, component=component) from exc

        results = await asyncio.gather(
            *(_stop_component(component) for component in component_list), return_exceptions=True
        )

        errors: list[Exception] = []
        for component, result in zip(component_list, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                error = LifecycleError(action=action, phase=phase_name, component=component)
                error.__cause__ = result
                errors.append(error)
            elif isinstance(result, Exception):
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result

        return errors

    async def start(self) -> None:
        async with self._lock:
            if self._started_phases:
                raise RuntimeError("Runtime components have already been started.")

            try:
                for phase in self._phases:
                    await self._start_phase(phase)
                    self._started_phases.append(phase)
            except BaseException:
                await wait_for_cleanup(
                    asyncio.create_task(
                        self._rollback_started_phases(), name="runtime_component_start_rollback"
                    )
                )
                raise

    async def stop(self) -> None:
        async with self._lock:
            if not self._started_phases:
                return

            errors: list[Exception] = []

            for phase in reversed(self._started_phases):
                phase_errors = await self._stop_components(
                    phase.components,
                    phase_name=phase.name,
                    action="stop",
                )
                errors.extend(phase_errors)

            self._started_phases.clear()

            if errors:
                raise ExceptionGroup(
                    "One or more runtime components failed to stop.",
                    errors,
                )
