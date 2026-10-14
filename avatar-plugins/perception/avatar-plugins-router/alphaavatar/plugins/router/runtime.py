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

from collections.abc import Sequence
from dataclasses import dataclass

from alphaavatar.agents.router import InteractionRouterBase, RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.lifecycle import LifecycleComponent, LifecycleGroup, LifecyclePhase

from .log import logger


@dataclass(slots=True)
class _ProcessorLifecycle(LifecycleComponent):
    processor: RouterProcessorBase

    async def on_start(self) -> None:
        await self.processor.start()

    async def on_stop(self) -> None:
        await self.processor.stop()


class InteractionRouterRuntime(InteractionRouterBase):
    """Manage Router processors in declaration order, without duplicating lifecycle mechanics."""

    def __init__(
        self, *, runtime: AvatarRuntime, processors: Sequence[RouterProcessorBase]
    ) -> None:
        super().__init__(runtime=runtime)
        self._processors = tuple(processors)
        names = [processor.name for processor in self._processors]
        if len(names) != len(set(names)):
            raise ValueError(f"Router processor names must be unique: {names}")

        self._lifecycle = LifecycleGroup(
            phases=tuple(
                LifecyclePhase.create(processor.name, (_ProcessorLifecycle(processor),))
                for processor in self._processors
            )
        )

    @property
    def processors(self) -> tuple[RouterProcessorBase, ...]:
        return self._processors

    async def on_start(self) -> None:
        await self._lifecycle.start()
        logger.info("Interaction Router started processors=%s", [p.name for p in self._processors])

    async def on_stop(self) -> None:
        await self._lifecycle.stop()
        logger.info("Interaction Router stopped")
