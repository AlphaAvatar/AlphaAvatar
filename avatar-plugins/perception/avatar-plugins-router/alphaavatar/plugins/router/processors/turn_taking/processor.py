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

from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import AnnotationKind
from alphaavatar.core.perception import PerceptionStreamKind

from ...log import logger
from .config import TurnTakingConfig
from .coordinator import TurnTakingCoordinator
from .fusion import AddressingFusion
from .models import create_turn_taking_model
from .policy import TurnTakingPolicy


class MultimodalTurnTakingProcessor(RouterProcessorBase):
    OBSERVATION_CONSUMER_ID = "router.turn_taking.observations"
    ANNOTATION_CONSUMER_ID = "router.turn_taking.annotations"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        config: TurnTakingConfig,
        required_addressing_sources: tuple[str, ...] = (),
    ) -> None:
        super().__init__(runtime=runtime)

        self._config = config

        self._model = create_turn_taking_model(
            config.model.name,
            inference_executor=runtime.inference,
        )
        self._coordinator = TurnTakingCoordinator(
            runtime=runtime,
            model=self._model,
            policy=TurnTakingPolicy(
                commit_threshold=config.policy.commit_threshold,
                interruption_enabled=config.interruption.enabled,
                audio_only_speech_start_interrupt=config.interruption.audio_only_speech_start,
                respond_to_group=config.policy.respond_to_group,
            ),
            fusion=AddressingFusion(conflict_margin=config.fusion.conflict_margin),
            addressing_wait_sec=config.addressing_wait_sec,
            transcript_wait_sec=config.transcript_wait_sec,
            max_hold_sec=config.max_hold_sec,
            unsegmented_alignment_sec=config.unsegmented_alignment_sec,
            required_addressing_sources=required_addressing_sources,
        )

        self._tasks: tuple[asyncio.Task[None], ...] = ()
        self._started = False

    @property
    def name(self) -> str:
        return "turn_taking"

    async def _consume_observations(self) -> None:
        streams = {
            PerceptionStreamKind.SPEECH,
            PerceptionStreamKind.TEXT,
        }

        while True:
            try:
                await self._runtime.perception.wait_for_pending_observations(
                    consumer_id=self.OBSERVATION_CONSUMER_ID,
                    streams=streams,
                )
                window = self._runtime.perception.take_pending_observations(
                    consumer_id=self.OBSERVATION_CONSUMER_ID,
                    streams=streams,
                )

                if window.has_gap:
                    logger.warning(
                        "Turn Taking observed perception gap missed=%s",
                        window.missed_count,
                    )
                    await self._coordinator.reset()

                for observation in window.observations:
                    try:
                        self._coordinator.handle_observation(observation)
                    except Exception:
                        logger.exception(
                            "Turn Taking failed observation_id=%s kind=%s",
                            observation.observation_id,
                            observation.kind,
                        )

                self._runtime.perception.commit_observations(window)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Turn Taking observation consumer failed")
                await asyncio.sleep(0.05)

    async def _consume_annotations(self) -> None:
        while True:
            try:
                await self._runtime.perception.wait_for_pending_annotations(
                    consumer_id=self.ANNOTATION_CONSUMER_ID,
                )
                batch = self._runtime.perception.take_pending_annotations(
                    consumer_id=self.ANNOTATION_CONSUMER_ID,
                    predicate=lambda annotation: (
                        annotation.kind == AnnotationKind.INTERACTION_ADDRESSING_EVIDENCE
                    ),
                    limit=32,
                )

                if batch.has_gap:
                    logger.warning(
                        "Turn Taking missed addressing annotations missed=%s",
                        batch.missed_count,
                    )
                    self._coordinator.handle_annotation_gap()

                for event in batch.items:
                    try:
                        self._coordinator.handle_annotation(event)
                    except Exception:
                        logger.exception(
                            "Turn Taking failed addressing event_id=%s",
                            event.event_id,
                        )

                self._runtime.perception.commit_annotations(
                    consumer_id=self.ANNOTATION_CONSUMER_ID,
                    cursor_seq=batch.cursor_seq,
                )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Turn Taking annotation consumer failed")
                await asyncio.sleep(0.05)

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        self._tasks = (
            asyncio.create_task(
                self._consume_observations(),
                name="router_turn_taking_observations",
            ),
            asyncio.create_task(
                self._consume_annotations(),
                name="router_turn_taking_annotations",
            ),
        )

        logger.info(
            "Multimodal Turn Taking started model=%s",
            self._model.name,
        )

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False

        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks = ()
        await self._coordinator.reset()

        self._runtime.perception.clear_observation_consumer(
            self.OBSERVATION_CONSUMER_ID,
            streams={
                PerceptionStreamKind.SPEECH,
                PerceptionStreamKind.TEXT,
            },
        )
        self._runtime.perception.clear_annotation_consumer(self.ANNOTATION_CONSUMER_ID)

        logger.info("Multimodal Turn Taking stopped")
