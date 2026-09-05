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
from typing import Protocol

from alphaavatar.agents.log import logger
from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.agents.router import (
    TurnTakingAction,
    TurnTakingDecision,
    TurnTakingMode,
)
from alphaavatar.agents.runtime import (
    AvatarRuntime,
    TurnInputModality,
    TurnSnapshot,
)
from alphaavatar.core.env import AnnotationKind, EnvObservation, ObservationKind
from alphaavatar.core.media import TextPayload
from alphaavatar.core.output import OutputLane
from alphaavatar.core.perception import PerceptionEvent


class AvatarTurnSink(Protocol):
    async def submit_turn(
        self,
        snapshot: TurnSnapshot,
        decision: TurnTakingDecision,
    ) -> None: ...

    async def interrupt(
        self,
        decision: TurnTakingDecision,
    ) -> None: ...


class AvatarTurnController(AvatarRuntimePlugin):
    CONSUMER_ID = "avatar.turn_controller"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        sink: AvatarTurnSink,
    ) -> None:
        self._runtime = runtime
        self._sink = sink
        self._task: asyncio.Task[None] | None = None

    @staticmethod
    def _modality(mode: TurnTakingMode) -> TurnInputModality:
        if mode == TurnTakingMode.AUDIO_ONLY:
            return TurnInputModality.AUDIO
        if mode == TurnTakingMode.VISUAL_ONLY:
            return TurnInputModality.IMAGE
        return TurnInputModality.MULTIMODAL

    def _observations(
        self,
        decision: TurnTakingDecision,
    ) -> tuple[EnvObservation, ...]:
        observations: list[EnvObservation] = []
        seen: set[str] = set()

        for observation_id in decision.input_observation_ids:
            if observation_id in seen:
                continue

            observation = self._runtime.perception.timeline.get_observation(
                observation_id=observation_id
            )
            if observation is not None:
                observations.append(observation)
                seen.add(observation_id)

        return tuple(observations)

    @staticmethod
    def _text(observations: tuple[EnvObservation, ...]) -> str | None:
        parts: list[str] = []

        for observation in observations:
            if observation.kind not in {
                ObservationKind.TRANSCRIPT_SEGMENT,
                ObservationKind.TEXT_INPUT,
            }:
                continue

            payload = observation.payload
            if not isinstance(payload, TextPayload):
                continue

            text = payload.text.strip()
            if text:
                parts.append(text)

        return " ".join(parts) or None

    @staticmethod
    def _started_at(
        observations: tuple[EnvObservation, ...],
        event: PerceptionEvent,
    ):
        if not observations:
            return event.time_range.start

        return min(
            (observation.time_range.start for observation in observations),
            key=lambda value: value.monotonic_ns,
        )

    async def _interrupt(self, decision: TurnTakingDecision) -> None:
        reason = decision.reason or "avatar_directed_barge_in"
        metadata = {
            "turn_candidate_id": decision.turn_candidate_id,
            "candidate_revision": decision.candidate_revision,
        }

        operations = (
            (
                "livekit_response",
                self._sink.interrupt(decision),
            ),
            (
                "assistant_output",
                self._runtime.output.interrupt(
                    lane=OutputLane.ASSISTANT,
                    reason=reason,
                    metadata=metadata,
                ),
            ),
            (
                "transient_output",
                self._runtime.output.interrupt(
                    lane=OutputLane.TRANSIENT,
                    reason=reason,
                    metadata=metadata,
                ),
            ),
        )

        results = await asyncio.gather(
            *(operation for _, operation in operations),
            return_exceptions=True,
        )

        for (label, _), result in zip(operations, results, strict=True):
            if isinstance(result, Exception):
                logger.warning(
                    "Avatar output interruption failed target=%s error=%s",
                    label,
                    result,
                )

    async def _commit(
        self,
        event: PerceptionEvent,
        decision: TurnTakingDecision,
    ) -> None:
        observations = self._observations(decision)
        text = self._text(observations)

        if not text:
            logger.error(
                "Committed turn has no transcript turn_candidate_id=%s",
                decision.turn_candidate_id,
            )
            return

        annotation = event.annotation
        snapshot = self._runtime.turn.commit_event_input(
            input_id=decision.turn_candidate_id,
            modality=self._modality(decision.turn_mode),
            text=text,
            started_at=self._started_at(observations, event),
            committed_at=event.time_range.end,
            cutoff_sequence=event.sequence,
            input_observation_ids=decision.input_observation_ids,
            metadata={
                "candidate_revision": decision.candidate_revision,
                "decision_event_id": event.event_id,
                "decision_event_sequence": event.sequence,
                "decision_annotation_id": (
                    annotation.annotation_id if annotation is not None else None
                ),
                "actor": (decision.actor.to_dict() if decision.actor is not None else None),
                "addressees": [addressee.to_dict() for addressee in decision.addressees],
                "reason": decision.reason,
            },
        )

        await self._runtime.output.start_turn(turn_id=snapshot.turn_id)
        await self._sink.submit_turn(snapshot, decision)

    async def _handle(self, event: PerceptionEvent) -> None:
        annotation = event.annotation
        if annotation is None:
            return

        decision = TurnTakingDecision.from_annotation(annotation)

        if decision.action == TurnTakingAction.COMMIT:
            await self._commit(event, decision)
            return

        if decision.action == TurnTakingAction.INTERRUPT:
            await self._interrupt(decision)

    async def _consume_loop(self) -> None:
        while True:
            try:
                await self._runtime.perception.wait_for_pending_annotations(
                    consumer_id=self.CONSUMER_ID,
                )

                batch = self._runtime.perception.take_pending_annotations(
                    consumer_id=self.CONSUMER_ID,
                    predicate=lambda annotation: (
                        annotation.kind == AnnotationKind.INTERACTION_TURN
                    ),
                    limit=1,
                )

                if batch.has_gap:
                    logger.warning(
                        "Avatar Turn Controller missed annotation events missed=%s",
                        batch.missed_count,
                    )

                if not batch.items:
                    self._runtime.perception.commit_annotations(
                        consumer_id=self.CONSUMER_ID,
                        cursor_seq=batch.cursor_seq,
                    )
                    continue

                await self._handle(batch.items[0])

                self._runtime.perception.commit_annotations(
                    consumer_id=self.CONSUMER_ID,
                    cursor_seq=batch.cursor_seq,
                )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Avatar Turn Controller failed")
                await asyncio.sleep(0.05)

    async def on_session_start(self) -> None:
        if self._task is not None:
            return

        self._task = asyncio.create_task(
            self._consume_loop(),
            name="avatar_turn_controller",
        )
        logger.info("Avatar Turn Controller started")

    async def on_session_stop(self) -> None:
        if self._task is None:
            return

        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

        self._runtime.perception.clear_annotation_consumer(self.CONSUMER_ID)
        logger.info("Avatar Turn Controller stopped")
