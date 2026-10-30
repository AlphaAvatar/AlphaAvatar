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
import time
from dataclasses import dataclass

from alphaavatar.agents.avatar.vision import FaceDetection, FaceDetectionResult
from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.router.enums import (
    AddressingEvidenceKind,
    AddressingMode,
    InteractionEntityKind,
)
from alphaavatar.agents.router.schemas import InteractionAddressingEvidence, InteractionEntityRef
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import AnnotationKind
from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSourceRef
from alphaavatar.core.perception.schemas import PerceptionEvent

from .config import VisualAddressingConfig
from .orientation import FaceOrientationEstimator

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VisualSubjectKey:
    source: PerceptionSourceRef
    entity_id: str | None


@dataclass(slots=True)
class VisualOrientationState:
    score: float | None = None
    samples: int = 0
    last_target: str | None = None
    last_published_ns: int = 0
    last_logged_at: float = 0.0
    suppressed_logs: int = 0


class VisualAddressingProcessor(RouterProcessorBase):
    CONSUMER_ID = "router.addressing.visual"
    SOURCE = "router.addressing.visual"

    def __init__(self, *, runtime: AvatarRuntime, config: VisualAddressingConfig) -> None:
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
    def _entity(observation: EnvObservation, face: FaceDetection) -> PerceptionEntityRef | None:
        return face.entity or observation.entity

    @staticmethod
    def _subject_key(
        observation: EnvObservation, entity: PerceptionEntityRef | None
    ) -> VisualSubjectKey:
        return VisualSubjectKey(
            source=observation.source, entity_id=entity.entity_id if entity is not None else None
        )

    def _select_faces(
        self, *, observation: EnvObservation, result: FaceDetectionResult
    ) -> tuple[FaceDetection, ...]:
        if len(result.faces) == 1 and observation.entity is not None:
            return result.faces

        counts: dict[str, int] = {}
        for face in result.faces:
            if face.entity is not None:
                key = face.entity.entity_id
                counts[key] = counts.get(key, 0) + 1
        return tuple(
            face
            for face in result.faces
            if face.entity is not None and counts[face.entity.entity_id] == 1
        )

    def _target(self, score: float) -> str | None:
        if score >= self._toward_threshold:
            return "avatar"

        if self._publish_away_evidence and score <= self._away_threshold:
            return "away"

        return None

    def _publish(
        self, *, observation: EnvObservation, face: FaceDetection, score: float, target: str
    ) -> None:
        entity = self._entity(observation, face)

        speaker = InteractionEntityRef(
            kind=InteractionEntityKind.PERSON,
            entity=entity,
            device_id=observation.device_id,
            source=observation.source,
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
            evidence.to_annotation(source=self.SOURCE, observation_id=observation.observation_id)
        )

    """Processor Loop"""

    def _handle_face(
        self,
        event: PerceptionEvent,
        observation: EnvObservation,
        result: FaceDetectionResult,
        face: FaceDetection,
    ) -> None:
        estimate = self._estimator.estimate(face=face, result=result)
        if estimate is None:
            return

        entity = self._entity(observation, face)
        key = self._subject_key(observation, entity)
        for previous in tuple(self._states):
            if previous.source.source_id != key.source.source_id:
                continue
            if previous.source.source_generation > key.source.source_generation:
                return
            if previous.source.source_generation < key.source.source_generation:
                self._states.pop(previous, None)

        if key not in self._states and len(self._states) >= 256:
            self._states.pop(next(iter(self._states)))

        state = self._states.setdefault(key, VisualOrientationState())

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

        self._publish(observation=observation, face=face, score=state.score, target=target)

        changed = target != state.last_target
        state.last_target = target
        state.last_published_ns = published_at_ns

        # Evidence freshness is unchanged; only diagnostics are rate-limited.
        now = time.monotonic()
        if not changed and now - state.last_logged_at < 10.0:
            state.suppressed_logs += 1
            return

        state.last_logged_at = now
        logger.debug(
            "Visual addressing evidence target=%s score=%.3f "
            "yaw=%.3f pitch=%.3f roll=%.2f observation_id=%s suppressed=%d",
            target,
            state.score,
            estimate.yaw_proxy,
            estimate.pitch_proxy,
            estimate.roll_deg,
            observation.observation_id,
            state.suppressed_logs,
        )
        state.suppressed_logs = 0

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
        for face in self._select_faces(observation=observation, result=result):
            self._handle_face(event, observation, result, face)

    async def _consume_loop(self) -> None:
        while True:
            try:
                await self._runtime.perception.wait_for_pending_annotations(
                    consumer_id=self.CONSUMER_ID
                )

                batch = self._runtime.perception.take_pending_annotations(
                    consumer_id=self.CONSUMER_ID,
                    predicate=lambda annotation: (annotation.kind == AnnotationKind.FACE_DETECTION),
                    limit=16,
                )

                if batch.has_gap:
                    logger.warning(
                        "Visual addressing missed face annotations missed=%s", batch.missed_count
                    )
                    self._states.clear()

                for event in batch.items:
                    try:
                        self._handle(event)
                    except Exception:
                        logger.exception("Visual addressing failed event_id=%s", event.event_id)

                self._runtime.perception.commit_annotations(
                    consumer_id=self.CONSUMER_ID, cursor_seq=batch.cursor_seq
                )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Visual addressing annotation consumer failed")
                await asyncio.sleep(0.05)

    """Runtime operations"""

    async def start(self) -> None:
        if self._task is not None:
            return

        self._task = asyncio.create_task(self._consume_loop(), name="router_visual_addressing")

        logger.info("Visual Addressing started")

    async def stop(self) -> None:
        if self._task is None:
            return

        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

        self._states.clear()

        self._runtime.perception.clear_annotation_consumer(self.CONSUMER_ID)

        logger.info("Visual Addressing stopped")
