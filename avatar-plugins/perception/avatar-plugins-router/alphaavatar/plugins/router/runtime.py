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

from alphaavatar.agents.router import InteractionRouterBase, RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime

from .log import logger


class InteractionRouterRuntime(InteractionRouterBase):
    """
    Interaction Router processor runtime.

    Concrete audio, video, multimodal and decision capabilities are implemented
    by independently managed RouterProcessorBase instances.
    """

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        processors: Sequence[RouterProcessorBase],
    ) -> None:
        super().__init__(runtime=runtime)

        names = [processor.name for processor in processors]
        if len(names) != len(set(names)):
            raise ValueError(f"Router processor names must be unique: {names}")

        self._processors = tuple(processors)
        self._started_processors: list[RouterProcessorBase] = []
        self._started = False

    @property
    def processors(self) -> tuple[RouterProcessorBase, ...]:
        return self._processors

    async def on_session_start(self) -> None:
        if self._started:
            return

        try:
            for processor in self._processors:
                await processor.start()
                self._started_processors.append(processor)
        except Exception:
            for processor in reversed(self._started_processors):
                try:
                    await processor.stop()
                except Exception:
                    logger.exception(
                        "Failed to rollback Router processor name=%s",
                        processor.name,
                    )

            self._started_processors.clear()
            raise

        self._started = True

        logger.info(
            "Interaction Router started processors=%s",
            [processor.name for processor in self._processors],
        )

    async def on_session_stop(self) -> None:
        if not self._started and not self._started_processors:
            return

        for processor in reversed(self._started_processors):
            try:
                await processor.stop()
            except Exception:
                logger.exception(
                    "Failed to stop Router processor name=%s",
                    processor.name,
                )

        self._started_processors.clear()
        self._started = False

        logger.info("Interaction Router stopped")
