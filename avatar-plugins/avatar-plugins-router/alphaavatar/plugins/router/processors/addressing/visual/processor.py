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
from dataclasses import dataclass

from alphaavatar.agents.avatar.vision import (
    FaceDetection,
    FaceDetectionResult,
)
from alphaavatar.agents.router import (
    AddressingEvidenceKind,
    AddressingMode,
    InteractionAddressingEvidence,
    InteractionEntityKind,
    InteractionEntityRef,
    RouterProcessorBase,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import (
    AnnotationKind,
    EnvObservation,
    PerceptionEntityRef,
    PerceptionSourceRef,
)
from alphaavatar.core.perception import PerceptionEvent

from ....log import logger
from .config import VisualAddressingConfig
from .orientation import FaceOrientationEstimator


@dataclass(frozen=True, slots=True)
class VisualSubjectKey:
    source: PerceptionSourceRef
    perception_entity_id: str | None
    transport_participant_id: str | None


@dataclass(slots=True)
class VisualOrientationState:
    score: float | None = None
    samples: int = 0
    last_target: str | None = None
    last_published_ns: int = 0


class VisualAddressingProcessor(RouterProcessorBase):
    CONSUMER_ID = "router.addressing.visual"
    SOURCE = "router.addressing.visual"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        config: VisualAddressingConfig,
    ) -> None:
        super().__init__(runtime=runtime)

        self._estimator = FaceOrientationEstimator(
            yaw_scale=config.yaw_scale,
            roll_scale_deg=config.roll_scale_deg,
            min_face_area_ratio=config.min_face_area_ratio,
        )
        self._toward_threshold = config.toward_threshold
        self._away_threshold = config.away_threshold
        self._ema_alpha = config.ema_alpha
        self._min_samples = config.min_samples
        self._republish_interval_ns = int(config.republish_interval_sec * 1_000_000_000)
        self._publish_away_evidence = config.publish_away_evidence

        self._states: dict[VisualSubjectKey, VisualOrientationState] = {}

        self._task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "visual_addressing"

    @staticmethod
    def _entity(
        observation: EnvObservation,
        face: FaceDetection,
    ) -> PerceptionEntityRef | None:
        return face.entity or observation.entity

    @staticmethod
    def _subject_key(
        observation: EnvObservation,
        entity: PerceptionEntityRef | None,
    ) -> VisualSubjectKey:
        return VisualSubjectKey(
            source=observation.source,
            perception_entity_id=(entity.perception_entity_id if entity is not None else None),
            transport_participant_id=(observation.transport_participant_id),
        )

    def _select_face(
        self,
        *,
        observation: EnvObservation,
        result: FaceDetectionResult,
    ) -> FaceDetection | None:
        if not result.faces:
            return None

        if len(result.faces) == 1:
            return result.faces[0]

        observation_entity = observation.entity

        if observation_entity is not None:
            matches = tuple(
                face
                for face in result.faces
                if (
                    face.entity is not None
                    and face.entity.perception_entity_id == observation_entity.perception_entity_id
                )
            )

            if len(matches) == 1:
                return matches[0]

        if result.selected_face_index is not None:
            selected = result.faces[result.selected_face_index]

            # In a multi-face frame, a selected bounding box alone does not
            # prove which current speaker it belongs to.
            if selected.entity is not None:
                return selected

        logger.debug(
            "Skip ambiguous multi-face visual addressing observation_id=%s faces=%s",
            observation.observation_id,
            len(result.faces),
        )
        return None

    def _target(self, score: float) -> str | None:
        if score >= self._toward_threshold:
            return "avatar"

        if self._publish_away_evidence and score <= self._away_threshold:
            return "away"

        return None

    def _publish(
        self,
        *,
        observation: EnvObservation,
        face: FaceDetection,
        score: float,
        target: str,
    ) -> None:
        entity = self._entity(observation, face)

        speaker = InteractionEntityRef(
            kind=InteractionEntityKind.PERSON,
            entity=entity,
            transport_participant_id=(observation.transport_participant_id),
        )

        if target == "avatar":
            addressees = (InteractionEntityRef(kind=InteractionEntityKind.AVATAR),)
            addressing_mode = AddressingMode.DIRECT
            confidence = score
            label = "camera_facing"
        else:
            addressees = ()
            addressing_mode = AddressingMode.UNKNOWN
            confidence = 1.0 - score
            label = "camera_away"

        evidence = InteractionAddressingEvidence(
            evidence_kind=AddressingEvidenceKind.VISUAL_ORIENTATION,
            speaker=speaker,
            addressees=addressees,
            addressing_mode=addressing_mode,
            confidence=confidence,
            evidence_label=label,
            raw_score=score,
            evidence_observation_ids=(observation.observation_id,),
        )

        self._runtime.perception.publish_annotation(
            evidence.to_annotation(
                source=self.SOURCE,
                observation_id=observation.observation_id,
            )
        )

    def _handle(self, event: PerceptionEvent) -> None:
        annotation = event.annotation

        if annotation is None:
            return

        observation_id = annotation.observation_id
        if observation_id is None:
            return

        observation = self._runtime.perception.timeline.get_observation(
            observation_id=observation_id
        )
        if observation is None:
            return

        result = FaceDetectionResult.from_annotation(annotation)
        face = self._select_face(
            observation=observation,
            result=result,
        )
        if face is None:
            return

        estimate = self._estimator.estimate(
            face=face,
            result=result,
        )
        if estimate is None:
            return

        entity = self._entity(observation, face)
        key = self._subject_key(observation, entity)
        state = self._states.setdefault(
            key,
            VisualOrientationState(),
        )

        state.score = (
            estimate.frontal_score
            if state.score is None
            else (self._ema_alpha * estimate.frontal_score + (1.0 - self._ema_alpha) * state.score)
        )
        state.samples += 1

        if state.samples < self._min_samples:
            return

        target = self._target(state.score)
        if target is None:
            return

        published_at_ns = event.time_range.end.monotonic_ns
        repeated_too_soon = target == state.last_target and (
            published_at_ns - state.last_published_ns < self._republish_interval_ns
        )
        if repeated_too_soon:
            return

        self._publish(
            observation=observation,
            face=face,
            score=state.score,
            target=target,
        )

        state.last_target = target
        state.last_published_ns = published_at_ns

        logger.debug(
            "Visual addressing evidence target=%s score=%.3f "
            "yaw=%.3f pitch=%.3f roll=%.2f observation_id=%s",
            target,
            state.score,
            estimate.yaw_proxy,
            estimate.pitch_proxy,
            estimate.roll_deg,
            observation.observation_id,
        )

    async def _consume_loop(self) -> None:
        while True:
            try:
                await self._runtime.perception.wait_for_pending_annotations(
                    consumer_id=self.CONSUMER_ID,
                )

                batch = self._runtime.perception.take_pending_annotations(
                    consumer_id=self.CONSUMER_ID,
                    predicate=lambda annotation: (annotation.kind == AnnotationKind.FACE_DETECTION),
                    limit=16,
                )

                if batch.has_gap:
                    logger.warning(
                        "Visual addressing missed face annotations missed=%s",
                        batch.missed_count,
                    )
                    self._states.clear()

                for event in batch.items:
                    try:
                        self._handle(event)
                    except Exception:
                        logger.exception(
                            "Visual addressing failed event_id=%s",
                            event.event_id,
                        )

                self._runtime.perception.commit_annotations(
                    consumer_id=self.CONSUMER_ID,
                    cursor_seq=batch.cursor_seq,
                )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Visual addressing annotation consumer failed")
                await asyncio.sleep(0.05)

    async def start(self) -> None:
        if self._task is not None:
            return

        self._task = asyncio.create_task(
            self._consume_loop(),
            name="router_visual_addressing",
        )

        logger.info("Visual Addressing started")

    async def stop(self) -> None:
        if self._task is None:
            return

        self._task.cancel()
        await asyncio.gather(
            self._task,
            return_exceptions=True,
        )
        self._task = None

        self._states.clear()

        self._runtime.perception.clear_annotation_consumer(self.CONSUMER_ID)

        logger.info("Visual Addressing stopped")
