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
"""Session-scoped runtime plugin lifecycle coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import SessionLifecycle


class PluginLifecycleError(RuntimeError):
    """Wrap a lifecycle error with plugin and phase information."""

    def __init__(
        self,
        *,
        action: str,
        phase: str,
        plugin: SessionLifecycle,
    ) -> None:
        plugin_name = f"{type(plugin).__module__}.{type(plugin).__qualname__}"
        super().__init__(
            f"Failed to {action} runtime plugin {plugin_name} in lifecycle phase {phase!r}"
        )


@dataclass(frozen=True, slots=True)
class LifecyclePhase:
    """
    A lifecycle phase whose plugins can run concurrently.

    Phases themselves are executed sequentially.
    """

    name: str
    plugins: tuple[SessionLifecycle, ...]

    @classmethod
    def create(
        cls,
        name: str,
        plugins: Iterable[SessionLifecycle],
    ) -> LifecyclePhase:
        return cls(name=name, plugins=tuple(plugins))


class RuntimePluginLifecycle:
    """
    Starts lifecycle phases in declaration order and stops them in reverse order.

    Plugins inside a phase start and stop concurrently.
    """

    def __init__(self, phases: Sequence[LifecyclePhase]) -> None:
        self._phases = tuple(phases)
        self._started_phases: list[LifecyclePhase] = []
        self._lock = asyncio.Lock()

        self._validate_unique_plugins()

    def _validate_unique_plugins(self) -> None:
        seen: set[int] = set()

        for phase in self._phases:
            for plugin in phase.plugins:
                plugin_id = id(plugin)
                if plugin_id in seen:
                    raise ValueError(
                        f"Runtime plugin {type(plugin).__qualname__} "
                        "appears in more than one lifecycle phase."
                    )
                seen.add(plugin_id)

    async def _start_phase(self, phase: LifecyclePhase) -> None:
        if not phase.plugins:
            return

        started_plugins: list[SessionLifecycle] = []

        async def _start_plugin(plugin: SessionLifecycle) -> None:
            try:
                logger.debug(
                    "Starting runtime plugin phase=%s plugin=%s",
                    phase.name,
                    type(plugin).__qualname__,
                )
                await plugin.on_session_start()
                started_plugins.append(plugin)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise PluginLifecycleError(action="start", phase=phase.name, plugin=plugin) from exc

        try:
            async with asyncio.TaskGroup() as task_group:
                tasks = {
                    task_group.create_task(
                        _start_plugin(plugin),
                        name=f"runtime_plugin_start:{phase.name}:{type(plugin).__qualname__}",
                    ): plugin
                    for plugin in phase.plugins
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
                            raise PluginLifecycleError(
                                action="start", phase=phase.name, plugin=tasks[task]
                            ) from exc
        except BaseException:
            await wait_for_cleanup(
                asyncio.create_task(
                    self._rollback_plugins(
                        tuple(reversed(started_plugins)),
                        phase_name=f"{phase.name}:partial_start_rollback",
                    ),
                    name=f"runtime_plugin_rollback:{phase.name}",
                )
            )
            raise

    async def _rollback_plugins(
        self, plugins: Iterable[SessionLifecycle], *, phase_name: str
    ) -> None:
        errors = await self._stop_plugins(plugins, phase_name=phase_name, action="rollback")
        for error in errors:
            logger.error("Runtime plugin rollback failed: %s", error, exc_info=error)

    async def _rollback_started_phases(self) -> None:
        for phase in reversed(self._started_phases):
            await self._rollback_plugins(phase.plugins, phase_name=f"{phase.name}:startup_rollback")
        self._started_phases.clear()

    async def _stop_plugins(
        self,
        plugins: Iterable[SessionLifecycle],
        *,
        phase_name: str,
        action: str,
    ) -> list[Exception]:
        plugin_list = tuple(plugins)
        if not plugin_list:
            return []

        async def _stop_plugin(plugin: SessionLifecycle) -> None:
            try:
                logger.debug(
                    "Stopping runtime plugin phase=%s plugin=%s",
                    phase_name,
                    type(plugin).__qualname__,
                )
                await plugin.on_session_stop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise PluginLifecycleError(action=action, phase=phase_name, plugin=plugin) from exc

        results = await asyncio.gather(
            *(_stop_plugin(plugin) for plugin in plugin_list), return_exceptions=True
        )

        errors: list[Exception] = []
        for plugin, result in zip(plugin_list, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                error = PluginLifecycleError(action=action, phase=phase_name, plugin=plugin)
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
                raise RuntimeError("Runtime plugins have already been started.")

            try:
                for phase in self._phases:
                    await self._start_phase(phase)
                    self._started_phases.append(phase)
            except BaseException:
                await wait_for_cleanup(
                    asyncio.create_task(
                        self._rollback_started_phases(), name="runtime_plugin_start_rollback"
                    )
                )
                raise

    async def stop(self) -> None:
        async with self._lock:
            if not self._started_phases:
                return

            errors: list[Exception] = []

            for phase in reversed(self._started_phases):
                phase_errors = await self._stop_plugins(
                    phase.plugins,
                    phase_name=phase.name,
                    action="stop",
                )
                errors.extend(phase_errors)

            self._started_phases.clear()

            if errors:
                raise ExceptionGroup(
                    "One or more runtime plugins failed to stop.",
                    errors,
                )
