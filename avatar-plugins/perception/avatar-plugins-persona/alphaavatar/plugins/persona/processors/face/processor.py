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
import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import cv2
import numpy as np

from alphaavatar.agents.avatar.vision import FaceDetection, FaceDetectionResult, FaceKeypoints5
from alphaavatar.agents.constants import (
    FACE_INFERENCE_THRESHOLD,
    FACE_MATCH_THRESHOLD,
    VIDEO_PERSONA_INTERVAL_SEC,
)
from alphaavatar.agents.persona import PersonaProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import avatar_capability
from alphaavatar.agents.runtime.capability.enums import AvatarCapabilityName
from alphaavatar.core.env import EnvAnnotation, EnvObservation
from alphaavatar.core.env.enums import AnnotationKind, ObservationKind
from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSourceRef
from alphaavatar.core.media import PayloadFormatUnavailable, VideoFrame
from alphaavatar.core.media.codecs.video import bgr_to_video_frame, video_frame_to_bgr
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session.enums import IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import IdentityRequest, Participant

from ...log import logger
from ...runtime import PersonaRuntime
from .analysis_runner import FaceAnalysisRunner
from .cache import FaceCache
from .config import FaceConfig
from .model_files import FACE_MODEL_CONFIG
from .tracking import FaceTracks


@dataclass(frozen=True, slots=True)
class FaceFrameJob:
    observation: EnvObservation
    participants: Mapping[str, Participant]


@avatar_capability(
    name=AvatarCapabilityName.PERSONA_FACE_RECOGNITION,
    description=(
        "Can recognize previously known users from visible faces and infer face "
        "attributes when visual observations are available."
    ),
)
class FaceProcessor(PersonaProcessorBase):
    CONSUMER_ID = "persona.face_stream"
    SOURCE = "persona.face_stream"

    def __init__(
        self, *, runtime: AvatarRuntime, persona: PersonaRuntime, config: FaceConfig
    ) -> None:
        super().__init__(runtime=runtime, persona=persona)

        self._config = config
        self._face_config = FACE_MODEL_CONFIG[FaceAnalysisRunner.MODEL_TYPE]
        self._last_sample_ts: dict[PerceptionSourceRef, float] = {}
        self._tracks = FaceTracks(config)
        self._profile_caches: dict[str, FaceCache] = {}
        self._identity_slots = asyncio.Semaphore(config.identity_concurrency)

        self._det_score_threshold = self._face_config.det_thresh
        self._min_face_size = self._face_config.min_face_size
        self._jpeg_quality = self._face_config.jpeg_quality

        self._frame_q: asyncio.Queue[FaceFrameJob] = asyncio.Queue(maxsize=2)
        self._worker_task: asyncio.Task[None] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._renderer_registered = False

    @property
    def name(self) -> str:
        return "face"

    """Observation helpers"""

    def _enqueue_latest(self, job: FaceFrameJob) -> bool:
        try:
            self._frame_q.put_nowait(job)
            return True

        except asyncio.QueueFull:
            try:
                self._frame_q.get_nowait()
            except asyncio.QueueEmpty:
                pass

            try:
                self._frame_q.put_nowait(job)
                return True
            except asyncio.QueueFull:
                return False

    def _maybe_enqueue_observation(self, observation: EnvObservation) -> None:
        if observation.kind != ObservationKind.VIDEO_FRAME:
            return

        payload = observation.payload
        if payload is None or not payload.has(
            PayloadFormat.IMAGE_JPEG_BYTES, view=PayloadView.RAW, fallback_to_raw=False
        ):
            return

        timestamp = observation.time_range.end.monotonic_ns / 1_000_000_000
        source = observation.source
        if not self.runtime.participants.observe_source(source) or not self._tracks.activate(
            source
        ):
            return

        self._release_retired_tracks()
        for previous in tuple(self._last_sample_ts):
            if previous.source_id == source.source_id and previous != source:
                self._last_sample_ts.pop(previous)

        last_ts = self._last_sample_ts.get(source, 0.0)

        if VIDEO_PERSONA_INTERVAL_SEC > 0 and timestamp - last_ts < VIDEO_PERSONA_INTERVAL_SEC:
            return

        job = FaceFrameJob(observation, self.session_runtime.snapshot().participants)
        if not self._enqueue_latest(job):
            logger.debug(
                "Face frame queue full; drop frame source_id=%s generation=%s frame_id=%s",
                source.source_id,
                source.source_generation,
                observation.frame_id,
            )
            return

        self._last_sample_ts[source] = timestamp

    def _face_vector(self, face: dict[str, Any]) -> np.ndarray | None:
        bbox = face.get("bbox")
        if bbox is None or len(bbox) != 4 or face.get("embedding") is None:
            return None
        x1, y1, x2, y2 = (float(value) for value in bbox)
        if (
            float(face.get("det_score") or 0) < self._det_score_threshold
            or x2 - x1 < self._min_face_size
            or y2 - y1 < self._min_face_size
        ):
            return None
        vector = np.asarray(face["embedding"], dtype=np.float32)
        if vector.shape != (self._face_config.embedding_dim,) or not np.isfinite(vector).all():
            return None
        norm = float(np.linalg.norm(vector))
        return vector / norm if np.isfinite(norm) and norm > 0 else None

    def _release_retired_tracks(self) -> None:
        for source, entity in self._tracks.drain_retired():
            participant = self.runtime.participants.resolve(source=source, entity=entity)
            if participant is not None:
                self._profile_caches.pop(participant.participant_id, None)
            self.runtime.participants.release_entity(source, entity)

    """Annotation operations"""

    def _safe_face_annotations(
        self,
        faces: list[dict[str, Any]],
        *,
        entities: list[PerceptionEntityRef | None],
        selected_entity: PerceptionEntityRef | None,
    ) -> tuple[tuple[FaceDetection, ...], int | None]:
        safe_faces: list[FaceDetection] = []
        selected_index: int | None = None

        for face, entity in zip(faces, entities, strict=True):
            bbox = face.get("bbox")
            if bbox is None or len(bbox) != 4:
                continue

            keypoints = face.get("kps")

            if entity is not None and entity == selected_entity:
                selected_index = len(safe_faces)

            safe_faces.append(
                FaceDetection(
                    bbox=tuple(float(value) for value in bbox),
                    detection_confidence=float(face.get("det_score") or 0.0),
                    keypoints=(
                        FaceKeypoints5.from_sequence(keypoints) if keypoints is not None else None
                    ),
                    entity=entity,
                )
            )

        return tuple(safe_faces), selected_index

    def _publish_face_annotation(
        self,
        *,
        job: FaceFrameJob,
        faces: list[dict[str, Any]],
        entities: list[PerceptionEntityRef | None],
        image_width: int,
        image_height: int,
    ) -> None:
        safe_faces, selected_index = self._safe_face_annotations(
            faces, entities=entities, selected_entity=job.observation.entity
        )

        if not safe_faces:
            return

        result = FaceDetectionResult(
            image_width=image_width,
            image_height=image_height,
            faces=safe_faces,
            selected_face_index=selected_index,
        )

        self.perception_runtime.publish_annotation(
            result.to_annotation(source=self.SOURCE, observation_id=job.observation.observation_id)
        )

    def _render_face_annotation(
        self, observation: EnvObservation, annotation: EnvAnnotation
    ) -> None:
        if annotation.kind != AnnotationKind.FACE_DETECTION:
            return

        payload = observation.payload
        if payload is None:
            return

        try:
            # Prefer an already annotated frame so different renderers can
            # compose overlays instead of overwriting one another.
            source_frame = payload.get(
                PayloadFormat.VIDEO_FRAME, view=PayloadView.ANNOTATED, fallback_to_raw=True
            )
        except PayloadFormatUnavailable:
            logger.debug(
                "Cannot render face annotation because VIDEO_FRAME "
                "representation is unavailable observation_id=%s",
                observation.observation_id,
            )
            return

        if not isinstance(source_frame, VideoFrame):
            logger.warning(
                "Cannot render face annotation because VIDEO_FRAME representation "
                "has an invalid type observation_id=%s type=%s",
                observation.observation_id,
                type(source_frame).__name__,
            )
            return

        try:
            bgr = video_frame_to_bgr(source_frame)
        except Exception:
            logger.exception(
                "Failed to convert video frame for face rendering observation_id=%s",
                observation.observation_id,
            )
            return

        result = FaceDetectionResult.from_annotation(annotation)

        for face in result.faces:
            x1, y1, x2, y2 = (int(value) for value in face.bbox)

            cv2.rectangle(bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                bgr,
                f"face {face.detection_confidence:.2f}",
                (x1, max(0, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )

        try:
            annotated_frame = bgr_to_video_frame(bgr)
        except Exception:
            logger.exception(
                "Failed to build annotated video frame observation_id=%s",
                observation.observation_id,
            )
            return

        ok, encoded = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality])
        if not ok:
            logger.warning(
                "Failed to encode annotated face frame observation_id=%s",
                observation.observation_id,
            )
            return

        payload.put(PayloadFormat.VIDEO_FRAME, annotated_frame, view=PayloadView.ANNOTATED)
        payload.put(PayloadFormat.IMAGE_JPEG_BYTES, encoded.tobytes(), view=PayloadView.ANNOTATED)

        rendered_annotations = observation.metadata.setdefault("rendered_annotations", [])
        if annotation.annotation_id not in rendered_annotations:
            rendered_annotations.append(annotation.annotation_id)

    """Inference worker"""

    def _job_is_current(self, job: FaceFrameJob) -> bool:
        source = job.observation.source
        if (
            self.session_runtime.closed
            or not self._tracks.current(source)
            or not self.runtime.participants.source_is_current(source)
        ):
            return False
        return all(
            state.source_id != source.source_id or (state.source == source and state.available)
            for state in self.perception_runtime.get_source_states()
        )

    def _identity_is_current(
        self, job: FaceFrameJob, entity: PerceptionEntityRef, participant: Participant
    ) -> bool:
        current = self.runtime.participants.resolve(source=job.observation.source, entity=entity)
        return (
            self._job_is_current(job)
            and current is not None
            and current.participant_id == participant.participant_id
            and self.runtime.participants.accepts_identity(participant)
        )

    async def _resolve_face_vector(
        self,
        vector: np.ndarray,
        *,
        job: FaceFrameJob,
        entity: PerceptionEntityRef,
        participant: Participant,
        timeout: float | None = None,
    ) -> Participant | None:
        if not self._identity_is_current(job, entity, participant):
            return None

        user_id = await self.persona.store.search_face_vector(
            face_vector=vector, threshold=FACE_MATCH_THRESHOLD, timeout=timeout
        )
        if not self._identity_is_current(job, entity, participant):
            return None

        if user_id is not None:
            outcome = self.runtime.participants.bind_user(
                IdentityRequest(
                    participant_id=participant.participant_id,
                    user_id=user_id,
                    source=IdentitySource.PERCEPTION,
                    basis_sequence=participant.identity_sequence,
                    reason=f"Face vector matched the stored user above {FACE_MATCH_THRESHOLD}",
                )
            )
            if outcome not in (IdentityOutcome.APPLIED, IdentityOutcome.UNCHANGED):
                return None

        cache = self.persona.cache_for(participant.participant_id)
        if cache is None:
            return None

        cache.face_vector = vector
        return cache.participant

    def _participant_for(
        self, job: FaceFrameJob, entity: PerceptionEntityRef
    ) -> Participant | None:
        current = self.runtime.participants.resolve(source=job.observation.source, entity=entity)
        if current is not None:
            # Recognition uses the identity view captured before the model await.
            return job.participants.get(current.participant_id)

        try:
            return self.runtime.participants.ensure_entity(job.observation.source, entity)
        except (ValueError, RuntimeError):
            logger.debug("Face entity admission unavailable source=%s", job.observation.source)
            return None

    async def _update_face(
        self,
        job: FaceFrameJob,
        face: dict[str, Any],
        vector: np.ndarray,
        entity: PerceptionEntityRef,
        participant: Participant,
    ) -> None:
        async with self._identity_slots:
            current = await self._resolve_face_vector(
                vector,
                job=job,
                entity=entity,
                participant=participant,
                timeout=self._face_config.inference_timeout_sec,
            )
            if current is None or not self._identity_is_current(job, entity, current):
                return

            cache = self.persona.cache_for(current.participant_id)
            if cache is None:
                return

            if current.participant_id not in self._profile_caches:
                if len(self._profile_caches) >= self._config.max_tracks:
                    self._profile_caches.pop(next(iter(self._profile_caches)))
                self._profile_caches[current.participant_id] = FaceCache()

            profile_cache = self._profile_caches[current.participant_id]
            cache.profile_details = profile_cache.update_profile_detail(
                cache.profile_details,
                face,
                updated_at=datetime.fromtimestamp(self.runtime.clock.now().unix_seconds, UTC),
            )

    async def _inference_face_job(self, job: FaceFrameJob) -> None:
        start_time = time.perf_counter()
        if not self._job_is_current(job):
            return

        payload = job.observation.payload
        if payload is None:
            return

        try:
            image_bytes = payload.get(
                PayloadFormat.IMAGE_JPEG_BYTES, view=PayloadView.RAW, fallback_to_raw=False
            )
        except PayloadFormatUnavailable:
            logger.debug(
                "Skip face inference because raw JPEG "
                "representation is unavailable observation_id=%s",
                job.observation.observation_id,
            )
            return

        if not isinstance(image_bytes, bytes):
            logger.warning(
                "Skip face inference because JPEG representation "
                "has an invalid type observation_id=%s type=%s",
                job.observation.observation_id,
                type(image_bytes).__name__,
            )
            return

        results = await self.inference_executor.do_inference(
            FaceAnalysisRunner.INFERENCE_METHOD, image_bytes
        )
        if not self._job_is_current(job):
            return

        data: dict[str, Any] = json.loads(results.decode())
        faces = data.get("faces", [])
        if not faces:
            return

        inference_duration = time.perf_counter() - start_time
        if inference_duration > FACE_INFERENCE_THRESHOLD:
            logger.warning(
                "[FaceAnalysis] inference is slower than realtime duration=%.3fs threshold=%.3fs",
                inference_duration,
                FACE_INFERENCE_THRESHOLD,
            )

        # One frame inference supplies all faces. Identity work has its own bounded budget.
        candidates = faces[: self._config.max_faces]
        vectors = [self._face_vector(face) for face in candidates]
        explicit = [
            PerceptionEntityRef.from_dict(face["entity"])
            if isinstance(face.get("entity"), dict)
            else job.observation.entity
            if len(faces) == 1
            else None
            for face in candidates
        ]
        associated = self._tracks.associate(
            job.observation.source,
            vectors,
            explicit,
            at=job.observation.time_range.end.monotonic_ns / 1_000_000_000,
        )
        self._release_retired_tracks()
        entities = list(associated) + [None] * (len(faces) - len(candidates))
        updates = []
        for index, (face, vector, entity) in enumerate(
            zip(candidates, vectors, associated, strict=True)
        ):
            if entity is None:
                continue

            participant = self._participant_for(job, entity)
            if participant is None:
                entities[index] = None
            elif vector is not None:
                updates.append((face, vector, entity, participant))

        # Publish per-face evidence before remote identity lookups can delay visual routing.
        self._publish_face_annotation(
            job=job,
            faces=faces,
            entities=entities,
            image_width=int(data["image_width"]),
            image_height=int(data["image_height"]),
        )
        outcomes = await asyncio.gather(
            *(self._update_face(job, *update) for update in updates), return_exceptions=True
        )
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                logger.warning(
                    "Face identity lookup failed source=%s error=%s",
                    job.observation.source,
                    outcome,
                )

    """Processor Loop"""

    async def _inference_loop(self) -> None:
        while True:
            job = await self._frame_q.get()

            try:
                await self._inference_face_job(job)

            except asyncio.CancelledError:
                raise

            except Exception as error:
                observation = job.observation
                logger.warning(
                    "Face worker failed device_id=%s source=%s error=%s",
                    observation.device_id,
                    observation.source,
                    error,
                    exc_info=True,
                )

    async def _consume_loop(self) -> None:
        while True:
            try:
                await self.perception_runtime.wait_for_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={PerceptionStreamKind.VIDEO, PerceptionStreamKind.SCREEN},
                )

                window = self.perception_runtime.take_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={PerceptionStreamKind.VIDEO, PerceptionStreamKind.SCREEN},
                    require_payload=True,
                )

                try:
                    if window.has_gap:
                        logger.warning(
                            "Face stream observed visual gap missed=%s", window.missed_count
                        )

                    for observation in window.observations:
                        try:
                            self._maybe_enqueue_observation(observation)
                        except Exception:
                            logger.exception(
                                "Face stream failed to enqueue observation observation_id=%s",
                                observation.observation_id,
                            )

                finally:
                    self.perception_runtime.commit_observations(window)

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception("Face stream failed to consume perception observations")
                await asyncio.sleep(0.05)

    """Runtime operations"""

    async def _start(self) -> None:
        if not self._renderer_registered:
            self.perception_runtime.add_annotation_renderer(self._render_face_annotation)
            self._renderer_registered = True

        self._worker_task = asyncio.create_task(
            self._inference_loop(), name="persona_face_inference"
        )
        self._poll_task = asyncio.create_task(self._consume_loop(), name="persona_face_consumer")

        logger.info("Persona Face started consumer_id=%s", self.CONSUMER_ID)

    async def _stop(self, *, finalize: bool) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
            self._poll_task = None

        if self._worker_task is not None:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
            self._worker_task = None

        if self._renderer_registered:
            self.perception_runtime.remove_annotation_renderer(self._render_face_annotation)
            self._renderer_registered = False

        while not self._frame_q.empty():
            try:
                self._frame_q.get_nowait()
            except asyncio.QueueEmpty:
                break

        self.perception_runtime.clear_observation_consumer(
            self.CONSUMER_ID, streams={PerceptionStreamKind.VIDEO, PerceptionStreamKind.SCREEN}
        )

        self._last_sample_ts.clear()
        self._tracks.clear()
        self._release_retired_tracks()
        self._profile_caches.clear()

        logger.info("Persona Face stopped consumer_id=%s", self.CONSUMER_ID)
